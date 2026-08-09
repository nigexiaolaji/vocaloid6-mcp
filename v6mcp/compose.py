"""
旋律生成与混合改编（compose_song / mix_songs 的底层实现）。

MIDI-GPT 尚未训练完成，当前提供「降级模板旋律」路径：
  - 根据歌词音节数生成简单旋律（C 大调音阶内随机/固定走向）
  - 后续 MIDI-GPT 训练完成后，可无缝替换 generate() 的实现

输出：标准 MIDI（pretty_midi 生成），可被 midi2vpr.midi_to_vocaloid 消费。
"""

import os
import random
import tempfile

import pretty_midi

from .lyrics import to_phonemes

# C 大调音阶（适合 VOCALOID 主旋律的朴素模板）
_C_MAJOR = [60, 62, 64, 65, 67, 69, 71, 72]


def _syllable_count(lyrics: str | None, fallback: int = 8) -> int:
    """估算歌词音节数（用于决定音符数量）。"""
    if not lyrics:
        return fallback
    ph = [p for p in to_phonemes(lyrics) if p]
    return max(len(ph), 1)


def template_melody_midi(
    lyrics: str | None = None,
    tempo: float = 120.0,
    key_offset: int = 0,
    out_path: str | None = None,
    seed: int = 42,
) -> str:
    """
    降级模板旋律：按歌词音节数生成简单旋律 MIDI。

    @return: 生成的 .mid 路径
    """
    rng = random.Random(seed)
    count = _syllable_count(lyrics)

    pm = pretty_midi.PrettyMIDI(initial_tempo=float(tempo))
    inst = pretty_midi.Instrument(program=0)
    beat = 60.0 / float(tempo)
    dur = beat * 0.9

    # 简单旋律走向：从根音出发，音阶内游走，句尾回落
    scale = [p + key_offset for p in _C_MAJOR]
    note_idx = 0
    direction = 1
    for i in range(count):
        # 轻微随机游走，控制在小范围
        note_idx += rng.choice([-1, 0, 1]) * direction
        note_idx = max(0, min(len(scale) - 1, note_idx))
        if rng.random() < 0.15:
            direction *= -1
        pitch = scale[note_idx]
        inst.notes.append(
            pretty_midi.Note(
                velocity=90,
                pitch=pitch,
                start=i * beat,
                end=i * beat + dur,
            )
        )

    pm.instruments.append(inst)
    if not out_path:
        out_path = os.path.join(tempfile.gettempdir(), "template_melody.mid")
    pm.write(out_path)
    return out_path


def compose_song(
    lyrics: str | None = None,
    style: str | None = None,
    tempo: float = 120.0,
    key: int = 0,
    length_bars: int = 8,
    out_dir: str | None = None,
) -> dict:
    """
    MCP 工具 compose_song 的底层实现（降级模板路径）。

    @return: {status, midi_path, vsqx_path, note_count, tempo, elapsed_sec}
    """
    import time

    from .midi2vpr import midi_to_vocaloid

    t0 = time.time()
    out_dir = out_dir or tempfile.gettempdir()
    os.makedirs(out_dir, exist_ok=True)

    song_name = f"composed_{int(t0)}"
    midi_path = template_melody_midi(
        lyrics=lyrics,
        tempo=tempo,
        key_offset=key,
        out_path=os.path.join(out_dir, song_name + ".mid"),
    )

    result = midi_to_vocaloid(
        midi_path,
        lyrics=lyrics,
        song_name=song_name,
        tempo=tempo,
        out_dir=out_dir,
    )
    result.update(
        {
            "status": "ok",
            "midi_path": midi_path,
            "engine": "template",  # 后续切 MIDI-GPT 时改为 "midigpt"
            "elapsed_sec": round(time.time() - t0, 2),
        }
    )
    return result


def mix_songs(
    song_a_midi: str,
    song_b_midi: str,
    mode: str = "segment_ab",
    out_dir: str | None = None,
) -> dict:
    """
    MCP 工具 mix_songs 的底层实现（初版：A-B 分段拼接）。

    @param mode: segment_ab（A 前半 + B 后半拼接，初版）
    @return: {status, midi_path, vsqx_path, mode, note_count, elapsed_sec}
    """
    import time

    from .midi2vpr import midi_to_vocaloid

    t0 = time.time()
    if not os.path.exists(song_a_midi) or not os.path.exists(song_b_midi):
        raise FileNotFoundError("song_a/song_b MIDI 文件不存在")
    if mode != "segment_ab":
        raise ValueError(f"初版仅支持 segment_ab 模式，收到: {mode}")

    out_dir = out_dir or tempfile.gettempdir()
    os.makedirs(out_dir, exist_ok=True)
    out_mid = os.path.join(out_dir, f"mix_{int(t0)}.mid")

    pa = pretty_midi.PrettyMIDI(song_a_midi)
    pb = pretty_midi.PrettyMIDI(song_b_midi)
    bpm_a = pa.estimate_tempo()
    bpm_b = pb.estimate_tempo()

    # 拼接：A 全曲 + B 全曲（B 按 A 的 BPM 重新定位，简单平移）
    pm = pretty_midi.PrettyMIDI(initial_tempo=bpm_a)
    offset = pa.get_end_time() + 1.0  # 1 秒间隔
    for inst in pa.instruments:
        pm.instruments.append(inst)
    for inst in pb.instruments:
        new_inst = pretty_midi.Instrument(program=inst.program, is_drum=inst.is_drum, name=inst.name)
        for n in inst.notes:
            new_inst.notes.append(
                pretty_midi.Note(
                    velocity=n.velocity,
                    pitch=n.pitch,
                    start=n.start + offset,
                    end=n.end + offset,
                )
            )
        pm.instruments.append(new_inst)
    pm.write(out_mid)

    result = midi_to_vocaloid(out_mid, out_dir=out_dir)
    result.update(
        {
            "status": "ok",
            "midi_path": out_mid,
            "mode": mode,
            "tempo_a": round(bpm_a, 2),
            "tempo_b": round(bpm_b, 2),
            "elapsed_sec": round(time.time() - t0, 2),
        }
    )
    return result
