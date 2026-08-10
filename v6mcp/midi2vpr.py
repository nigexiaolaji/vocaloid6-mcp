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


def _resolve_bpm(pm: pretty_midi.PrettyMIDI, tempo: float | None = None) -> float:
    """解析 BPM：显式 tempo 优先 → MIDI tempo 事件 → estimate_tempo → 兜底 120。

    estimate_tempo 在音符少于 2 个时会抛 ValueError，这里统一防御。
    """
    if tempo and 30 < float(tempo) < 300:
        return float(tempo)
    try:
        _, tempos = pm.get_tempo_changes()
        if len(tempos):
            bpm = float(tempos[0])
            if 30 < bpm < 300:
                return bpm
    except Exception:
        pass
    try:
        est = pm.estimate_tempo()
        if 30 < est < 300:
            return est
    except Exception:
        pass
    return 120.0


def _pick_melody_track(pm: pretty_midi.PrettyMIDI):
    """取第一条有音符的非鼓轨作为主旋律。"""
    for inst in pm.instruments:
        if not inst.is_drum and len(inst.notes) > 0:
            return inst
    raise ValueError("MIDI 中没有找到非鼓旋律轨")


def _assign_lyrics(note_count: int, lyrics: str | None) -> list:
    """把歌词音素分配给音符；音符多于音节时循环重复歌词（保持演唱连贯），无歌词才用默认音。"""
    if lyrics:
        phonemes = [p for p in to_phonemes(lyrics) if p]
    else:
        phonemes = []
    out = []
    for i in range(note_count):
        if phonemes:
            out.append(phonemes[i % len(phonemes)])  # 循环铺满所有音符
        else:
            out.append(DEFAULT_LYRIC)
    return out


def _build_mixer(track_count: int = 1) -> list:
    """最小可用 mixer：masterUnit + 每个 vsTrack 对应的 vsUnit + monoUnit + stUnit。

    VOCALOID6 要求 mixer 中为每个 vsTrack 提供对应 vsUnit（音量/声像控制），
    缺失会导致编辑器拒绝打开文件。
    """
    vs_units = [
        # [tNo, iGin, plugs, sLvl, sEnable, m, s, pan, vol]
        [i, 0, [], 0, 0, 0, 0, 0, 0]
        for i in range(track_count)
    ]
    return [
        [0, [], [], 0, 0],          # masterUnit: oDev, plugs, plugSR, rLvl, vol
        vs_units,                    # vsUnits：每个 vsTrack 一个
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
    bpm = _resolve_bpm(pm, tempo)

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
        _build_mixer(track_count=len(vs_tracks)),  # mixer（每个 vsTrack 对应一个 vsUnit）
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


def _extract_note_data(pm: pretty_midi.PrettyMIDI, bpm: float, lyrics: str | None):
    """提取主旋律音符 → [(tick, dur, pitch, vel, lyric, phoneme)]，供 VSQX/VPR 共用。

    VOCALOID 的 lyric 字段应填假名（如 さ），phoneme 必须是空格分隔的
    音素序列（如 "s a"），否则歌词不渲染。
    """
    from .lyrics import to_syllables, to_vocaloid_phonemes

    mel = _pick_melody_track(pm)
    notes_sorted = sorted(mel.notes, key=lambda n: n.start)

    # 成对取（假名, 音素序列），过滤无法合成的字符
    pairs = []
    if lyrics:
        syllables = to_syllables(lyrics)
        phonemes = to_vocaloid_phonemes(lyrics)
        pairs = [
            (syl, ph)
            for syl, ph in zip(syllables, phonemes)
            if ph and not syl.startswith("[")
        ]
    out = []
    for i, n in enumerate(notes_sorted):
        if pairs:
            lyric, ph = pairs[i % len(pairs)]  # 循环铺满：音符多于歌词时重复演唱
        else:
            lyric = ph = DEFAULT_LYRIC
        out.append(
            (
                _sec_to_ticks(n.start, bpm),
                max(60, _sec_to_ticks(n.end - n.start, bpm)),
                int(n.pitch),
                max(1, min(127, int(n.velocity))),
                lyric,
                ph,
            )
        )
    return out


# V6 内置声库官方名单（vtb2 加密，compID 需在 V6 编辑器确认）
V6_BUILTIN_VOICES = [
    # (名字, 语言, 类型)
    ("HARUKA", "日语/英语/中文", "AI 女声"),
    ("AKITO", "日语/英语/中文", "AI 男声"),
    ("SARAH", "英语/日语/中文", "AI 女声"),
    ("ALLEN", "英语/日语/中文", "AI 男声"),
    ("Amy", "日语", "标准女声"),
    ("Chris", "日语", "标准男声"),
    ("Kaori", "日语", "标准女声"),
    ("Ken", "日语", "标准男声"),
]


def _discover_voicebanks() -> list:
    """扫描本机 VOCALOID 声库，返回 [(compID, name, kind)]。

    kind: "vvd"=真实发现的声库（vvd 文件） / "vtb2"=V6 内置声库（加密包）
    扫描位置：ProgramData\\Yamaha\\VXBeta\\voicebanks\\apd → E:\\VoiceDB → V6 Model 目录。
    """
    import glob

    roots = [
        os.path.expandvars(r"%ProgramData%\Yamaha\VXBeta\voicebanks\apd"),
        r"E:\VoiceDB",
        os.path.expandvars(r"%ProgramFiles%\Common Files\VOCALOID6\Model"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Common Files\VOCALOID6\Model"),
    ]
    banks = []
    seen = set()
    for root in roots:
        if not root or not os.path.isdir(root):
            continue
        # compID 目录可能在两级下：<root>/<声库组>/<compID>/ 或 <root>/<compID>/
        for d in sorted(glob.glob(os.path.join(root, "*")) + glob.glob(os.path.join(root, "*", "*"))):
            cid = os.path.basename(d)
            if not (len(cid) == 16 and cid.isalnum()) or cid in seen:
                continue
            # 声库名优先取 *.vvd 文件名；无 vvd 时尝试 *.vvd 同目录其他标记
            name = cid
            vvds = glob.glob(os.path.join(d, "*.vvd"))
            if vvds:
                name = os.path.splitext(os.path.basename(vvds[0]))[0]
            banks.append((cid, name, "vvd"))
            seen.add(cid)

    # 检测 V6 内置声库包（vtb2）：确认 V6 AI 声库已安装，但 compID 需编辑器确认
    model_dirs = [
        os.path.expandvars(r"%ProgramFiles%\Common Files\VOCALOID6\Model"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Common Files\VOCALOID6\Model"),
    ]
    vtb2_found = False
    for md in model_dirs:
        if md and os.path.isdir(md) and glob.glob(os.path.join(md, "**", "*.vtb2"), recursive=True):
            vtb2_found = True
            break
    if vtb2_found:
        banks.append(("__V6_BUILTIN__", "VOCALOID6 内置声库", "vtb2"))

    return banks or [("VOCALOID6", "VOCALOID6", "vvd")]


def list_voicebanks() -> list:
    """列出本机可用歌姬（MCP 工具 list_voicebanks 的底层实现）。

    @return: [{comp_id, name, kind, lang, type, usable}]
    """
    out = []
    for cid, name, kind in _discover_voicebanks():
        if kind == "vtb2":
            # 内置声库包：展开官方名单，compID 未定
            for vb_name, lang, vtype in V6_BUILTIN_VOICES:
                out.append(
                    {
                        "comp_id": None,
                        "name": vb_name,
                        "kind": "vtb2",
                        "lang": lang,
                        "type": vtype,
                        "usable": False,  # 需在 V6 编辑器确认 compID 后才能写入工程
                        "hint": "V6 内置 AI 声库（加密包），选中后请先在 V6 编辑器确认，或将 voice 指定为已发现的声库名",
                    }
                )
        else:
            out.append(
                {
                    "comp_id": cid,
                    "name": name,
                    "kind": kind,
                    "lang": "",
                    "type": "",
                    "usable": True,
                    "hint": "",
                }
            )
    return out


def _pick_voice(voice_comp_id: str | None, voice_name: str | None) -> tuple:
    """选择声库：显式 compID 优先 → 名字匹配（不区分大小写/包含）→ 第一个真实声库。

    @return: (compID, name)
    """
    banks = _discover_voicebanks()
    real = [(cid, nm) for cid, nm, kind in banks if kind == "vvd"]
    if voice_comp_id:
        return voice_comp_id, voice_name or voice_comp_id
    if voice_name:
        vn = voice_name.strip().lower()
        for cid, nm in real:
            if nm.lower() == vn or vn in nm.lower() or nm.lower() in vn:
                return cid, nm
        # 找不到精确/包含匹配：仍以用户指定名字为准（V6 打开时如无该声库会提示）
        return real[0][0] if real else "VOCALOID6", voice_name
    cid, name = real[0] if real else ("VOCALOID6", "VOCALOID6")
    return cid, name


def midi_to_vpr(
    midi_path: str,
    lyrics: str | None = None,
    song_name: str | None = None,
    tempo: float | None = None,
    out_path: str | None = None,
    voice_comp_id: str | None = None,
    voice_name: str | None = None,
    emotion: str | None = None,
) -> dict:
    """
    MIDI → VOCALOID6 原生工程文件 .vpr（zip + Project/sequence.json）。

    VOCALOID6 的原生格式是 VPR（JSON），VSQX(XML) 仅为兼容读取且校验严格。
    直接生成 VPR 可保证 V6 正常打开。声库默认自动发现本机安装的真实声库。

    @param emotion: 情感（happy/sad/gentle/passionate/rock/calm 或中文别名），
                    控制音符力度/开音/颤音与 Part 级控制器曲线
    @return: {vpr_path, note_count, tempo, duration_sec, note_data, voice_comp_id}
    """
    import json
    import zipfile

    from .emotion import apply_to_note, build_controllers, emotion_params

    if not os.path.exists(midi_path):
        raise FileNotFoundError(f"MIDI 文件不存在: {midi_path}")

    pm = pretty_midi.PrettyMIDI(midi_path)
    bpm = _resolve_bpm(pm, tempo)

    song = song_name or os.path.splitext(os.path.basename(midi_path))[0]
    if not out_path:
        out_path = os.path.join(os.path.dirname(os.path.abspath(midi_path)), song + ".vpr")

    comp_id, name = _pick_voice(voice_comp_id, voice_name)
    note_data = _extract_note_data(pm, bpm, lyrics)
    if not note_data:
        raise ValueError("旋律轨没有可导出的音符")

    total_ticks = _sec_to_ticks(pm.get_end_time(), bpm) or 7680
    tempo_val = int(bpm * 100)
    ep = emotion_params(emotion)  # {"_key","_label",velocity,opening,vibrato_type,vibrato_dur,controllers}

    def _note_dict(nd):
        """按情感生成音符字典（velocity/exp/vibrato 来自情感映射）。"""
        v = nd[3]  # MIDI velocity 作基线
        velocity = ep["velocity"] if emotion else max(1, min(127, v))
        opening = ep["opening"]
        vt = ep["vibrato_type"]
        vd = ep["vibrato_dur"]
        return {
            "lyric": nd[4],
            # 真实 V6 工程：phoneme 为音素字符串（如 "y o"）；null 会导致歌词不显示
            "phoneme": nd[5],
            "isProtected": False,
            "pos": nd[0],
            "duration": nd[1],
            "number": nd[2],
            "velocity": velocity,
            "exp": {"opening": opening},
            # singingSkill 必须为有效对象（参考真实工程），null 会导致音符不渲染
            "singingSkill": {
                "duration": 0,
                "weight": {"pre": 64, "post": 64},
            },
            "vibrato": {"type": vt, "duration": vd},
        }

    seq = {
        "version": {"major": 5, "minor": 4, "revision": 0},
        "vender": "Yamaha Corporation",
        "title": song,
        "masterTrack": {
            "samplingRate": 44100,
            "loop": {"isEnabled": False, "begin": 0, "end": total_ticks},
            "tempo": {
                "isFolded": False,
                "height": 0.0,
                "global": {"isEnabled": False, "value": tempo_val},
                "events": [{"pos": 0, "value": tempo_val}],
            },
            "timeSig": {"isFolded": False, "events": [{"bar": 0, "numer": 4, "denom": 4}]},
            "volume": {"isFolded": False, "height": 0.0, "events": [{"pos": 0, "value": 0}]},
        },
        "voices": [{"compID": comp_id, "name": name}],
        "tracks": [
            {
                "type": 0,
                "name": "Track1",
                "color": 0,
                "busNo": 0,
                "isFolded": False,
                "height": 0.0,
                "volume": {"isFolded": False, "height": 0.0, "events": [{"pos": 0, "value": 0}]},
                "panpot": {"isFolded": False, "height": 0.0, "events": [{"pos": 0, "value": 0}]},
                "isMuted": False,
                "isSoloMode": False,
                "parts": [
                    {
                        "name": "Part1",
                        "pos": 0,
                        "duration": total_ticks,
                        "styleName": "VOCALOID2 Compatible Style",
                        # 真实 V6 工程：part.voice 只有 compID + langID（0=日语），不含 name
                        "voice": {"compID": comp_id, "langID": 0},
                        "midiEffects": [],
                        "notes": [_note_dict(nd) for nd in note_data],
                        "controllers": build_controllers(emotion, total_ticks),
                    }
                ],
            }
        ],
    }

    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("Project/sequence.json", json.dumps(seq, ensure_ascii=False, indent=2))

    return {
        "vpr_path": out_path,
        "note_count": len(note_data),
        "tempo": round(bpm, 2),
        "duration_sec": round(pm.get_end_time(), 2),
        "note_data": note_data,
        "emotion": ep["_key"],
        "emotion_label": ep["_label"],
    }


def midi_to_vocaloid(
    midi_path: str,
    lyrics: str | None = None,
    song_name: str | None = None,
    tempo: float | None = None,
    out_dir: str | None = None,
    voice: str | None = None,
    emotion: str | None = None,
) -> dict:
    """
    MCP 工具 midi_to_vocaloid 的底层实现：MIDI → V6 原生 .vpr（主）+ .vsqx（备）。

    @param voice: 歌姬名（如 "MIKU_V4X_Original_EVEC" / "HARUKA"）或 compID；缺省自动发现本机声库
    @param emotion: 情感（happy/sad/gentle/passionate/rock/calm 或中文别名）
    @return: 结构化结果（含 vpr_path/vsqx_path 与统计）
    """
    t0 = time.time()
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
        song = song_name or os.path.splitext(os.path.basename(midi_path))[0]
        vpr_path = os.path.join(out_dir, song + ".vpr")
        vsqx_path = os.path.join(out_dir, song + ".vsqx")
    else:
        vpr_path = vsqx_path = None

    voice_comp_id = None
    voice_name = None
    if voice:
        # 允许用户直接传 compID（16 位大写字母数字）或名字
        if len(voice) == 16 and voice.isalnum() and voice.isupper():
            voice_comp_id = voice
        else:
            voice_name = voice

    result = midi_to_vpr(midi_path, lyrics, song_name, tempo, vpr_path,
                         voice_comp_id=voice_comp_id, voice_name=voice_name,
                         emotion=emotion)
    # 兼容兜底：同时产出 vsqx（部分场景仍可能需要）
    try:
        vsqx_result = midi_to_vsqx(midi_path, lyrics, song_name, tempo, vsqx_path)
        result["vsqx_path"] = vsqx_result["vsqx_path"]
    except Exception as e:
        result["vsqx_path"] = None
        result["vsqx_warning"] = str(e)

    result["status"] = "ok"
    result["elapsed_sec"] = round(time.time() - t0, 2)
    return result
