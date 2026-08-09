"""
MIDI → VOCALOID6 工程文件（.vsqx，V6 官方支持读取）核心转换。

使用 vendored 的 vsqxt 库生成 vsq4 XML 工程文件：
  - 从 MIDI 提取主旋律轨（第一条非鼓 melodic 轨）
  - 音符转 tick（resolution=480）
  - 歌词（音素）按时间对齐到音符
  - 输出 .vsqx（V6 可读；注：vsqxt 仅支持写 VSQX，VPR 后续阶段再补）

注意：VOCALOID6 官方「可读取」格式包含 VSQX（见官方规格页），
因此生成的 .vsqx 可直接被 V6 打开渲染。
"""

import os
import time

import pretty_midi

from vsqxt import VSQX4
from vsqxt.base import VNOTE

from .lyrics import to_phonemes, to_syllables

RESOLUTION = 480  # 每四分音符 tick 数（VSQX 标准）

# vsq4 必需的基础结构（参考 vsqxt 源码示例）
VENDER = "Yamaha corporation"
VERSION = "4.0.0.3"
S_PLUG = ["ACA9C502-A04B-42b5-B2EB-5CEA36D16FCE", "VOCALOID2 Compatible Style", "3.0.0.1"]
P_STYLE = [50, 8, 0, 50, 0, 127, 0]  # accent,bendDep,bendLen,decay,fallPort,opening,risePort
SINGER = [0, 0, 5]  # [t, bs, pc]
DEFAULT_LYRIC = "a"  # 无歌词时的兜底音节


def _sec_to_ticks(sec: float, bpm: float) -> int:
    """秒 → tick（480 分辨率）。"""
    return int(round(sec * RESOLUTION * bpm / 60.0))


def _pick_melody_track(pm: pretty_midi.PrettyMIDI):
    """取第一条有音符的非鼓轨作为主旋律。"""
    for inst in pm.instruments:
        if not inst.is_drum and len(inst.notes) > 0:
            return inst
    raise ValueError("MIDI 中没有找到非鼓旋律轨")


def _assign_lyrics(note_count: int, lyrics: str | None) -> list:
    """把歌词音素分配给音符；不足补默认音节，多余截断。"""
    if lyrics:
        phonemes = [p for p in to_phonemes(lyrics) if p]
    else:
        phonemes = []
    out = []
    for i in range(note_count):
        if i < len(phonemes):
            out.append(phonemes[i])
        else:
            out.append(DEFAULT_LYRIC)
    return out


def _build_mixer() -> list:
    """最小可用 mixer：masterUnit + 空 vsUnits + monoUnit + stUnit。"""
    return [
        [0, [], [], 0, 0],          # masterUnit: oDev, plugs, plugSR, rLvl, vol
        [],                          # vsUnits（空，__write_vsUnit__ 处理空列表）
        [0, [], 0, 0, 0, 0, 0, 0],   # monoUnit: iGin, plugs, sLvl, sEnable, m, s, pan, vol
        [0, [], 0, 0, 0],            # stUnit: iGin, plugs, m, s, vol
    ]


def midi_to_vsqx(
    midi_path: str,
    lyrics: str | None = None,
    song_name: str | None = None,
    tempo: float | None = None,
    out_path: str | None = None,
) -> dict:
    """
    MIDI → .vsqx 工程文件。

    @param midi_path: 输入 MIDI 路径
    @param lyrics: 歌词文本（日文假名/罗马音）；None 时用默认音节
    @param song_name: 歌曲名（缺省用文件名）
    @param tempo: 覆盖 BPM（缺省用 MIDI 内 tempo）
    @param out_path: 输出 .vsqx 路径（缺省与输入同目录同名 .vsqx）
    @return: {vsqx_path, note_count, tempo, lyric_count, duration_sec}
    """
    if not os.path.exists(midi_path):
        raise FileNotFoundError(f"MIDI 文件不存在: {midi_path}")

    pm = pretty_midi.PrettyMIDI(midi_path)
    mel = _pick_melody_track(pm)

    # 取 tempo（MIDI 元数据优先，兜底估计值）
    bpm = tempo or (pm.estimate_tempo() if pm.get_tempo_changes()[1] else 120.0)
    if bpm <= 0 or bpm > 300:
        bpm = 120.0

    song = song_name or os.path.splitext(os.path.basename(midi_path))[0]
    if not out_path:
        out_path = os.path.join(os.path.dirname(os.path.abspath(midi_path)), song + ".vsqx")

    # 音符排序 → tick 坐标
    notes_sorted = sorted(mel.notes, key=lambda n: n.start)
    lyric_ph = _assign_lyrics(len(notes_sorted), lyrics)

    vnotes = []
    for i, n in enumerate(notes_sorted):
        # vsPart 内部会再包一层 VNOTE，期望 8 元原始参数列表
        # [t, dur, n, v, y, p, nstyle, lock]
        # nstyle = [accent,bendDep,bendLen,decay,fallPort,opening,risePort,vibLen,vibType,vibDep,vibRate]
        nstyle = [50, 8, 0, 50, 0, 127, 0, 0, 0, [], []]
        vnotes.append(
            [
                _sec_to_ticks(n.start, bpm),
                max(60, _sec_to_ticks(n.end - n.start, bpm)),
                int(n.pitch),
                max(1, min(127, int(n.velocity))),
                lyric_ph[i],
                lyric_ph[i],
                nstyle,
                "",  # lock
            ]
        )

    if not vnotes:
        raise ValueError("旋律轨没有可导出的音符")

    total_ticks = _sec_to_ticks(pm.get_end_time(), bpm) or (vnotes[-1].return_param()[0] + vnotes[-1].return_param()[1])

    # masterTrack: [seqName, comment, resolution, preMeasure, TimeSigs, Tempos]
    master_track = [song, "", RESOLUTION, 0, [[0, 4, 4]], [[0, int(bpm * 100)]]]
    # vsTrack: [tNo, name, comment, [vsPart]]
    vs_part = [
        0, total_ticks, "Part1", "",       # t, playTime, name, comment
        S_PLUG, P_STYLE, SINGER, [], vnotes, 0,  # sPlug, pStyle, singer, ccs, notes, plane
    ]
    vs_tracks = [[0, "Track1", "", [vs_part]]]

    vsqx_params = [
        VENDER, VERSION,
        # vVoiceTable：必须与 vsPart 的 singer [t, bs, pc] 对应（bs=0, pc=5），
        # 空表会导致 VOCALOID6 找不到歌手而拒绝打开文件
        [[0, 5, "VOCALOID6", "VOCALOID6", [0, 0, 0, 0, 0]]],
        _build_mixer(),            # mixer
        master_track,
        vs_tracks,
        [],                        # monoTrack
        [],                        # stTrack
        # aux：content 不能为空字符串（vsqxt 的 read() 对空 content 会崩；V6 可接受占位）
        ["AUX_VST_HOST_CHUNK_INFO", "VlNDSwcAAAADAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"],
    ]

    vsqx = VSQX4(vsqx_params)
    vsqx.write(out_path, mode="w")

    return {
        "vsqx_path": out_path,
        "note_count": len(vnotes),
        "lyric_count": len([p for p in lyric_ph if p != DEFAULT_LYRIC]),
        "tempo": round(bpm, 2),
        "duration_sec": round(pm.get_end_time(), 2),
    }


def midi_to_vocaloid(
    midi_path: str,
    lyrics: str | None = None,
    song_name: str | None = None,
    tempo: float | None = None,
    out_dir: str | None = None,
) -> dict:
    """
    MCP 工具 midi_to_vocaloid 的底层实现：MIDI → .vsqx。
    @return: 结构化结果（含 vsqx_path 与统计）
    """
    t0 = time.time()
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
        song = song_name or os.path.splitext(os.path.basename(midi_path))[0]
        out_path = os.path.join(out_dir, song + ".vsqx")
    else:
        out_path = None
    result = midi_to_vsqx(midi_path, lyrics, song_name, tempo, out_path)
    result["status"] = "ok"
    result["elapsed_sec"] = round(time.time() - t0, 2)
    return result
