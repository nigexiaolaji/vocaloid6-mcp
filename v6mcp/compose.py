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

# 音阶表（以 C 为基准的相对音程；key_offset 做整体平移）
_SCALES = {
    "major":      [0, 2, 4, 5, 7, 9, 11, 12],   # 大调
    "minor":      [0, 2, 3, 5, 7, 8, 10, 12],   # 自然小调
    "pentatonic": [0, 2, 4, 7, 9, 12, 14, 16],  # 五声（宫调式）
    "minor_penta":[0, 3, 5, 7, 10, 12, 15, 17], # 小调五声
}

# 风格 → (跳进范围, 音符时值倍率, 方向翻转概率)
_STYLES = {
    "default": {"jump": [-1, 0, 1], "dur_mult": 1.0, "flip": 0.15},
    "calm":    {"jump": [-1, 0, 1], "dur_mult": 2.0, "flip": 0.08},   # 舒缓：长音、小跳进
    "lively":  {"jump": [-2, -1, 1, 2], "dur_mult": 0.5, "flip": 0.25}, # 活泼：大跳进、短音
}

# 调名 → 半音偏移（支持 C/D/F#m 等）
_KEYS = {
    "C": 0, "C#": 1, "Db": 1, "D": 2, "D#": 3, "Eb": 3, "E": 4, "F": 5,
    "F#": 6, "Gb": 6, "G": 7, "G#": 8, "Ab": 8, "A": 9, "A#": 10, "Bb": 10, "B": 11,
}


def _resolve_key(key) -> int:
    """把 key 参数解析为半音偏移：支持数字（0-11）或调名（C/Dm/Eb 等）。"""
    if key is None:
        return 0
    if isinstance(key, (int, float)):
        return int(key) % 12
    k = str(key).strip().replace("m", "").replace("M", "")
    return _KEYS.get(k, 0)


def _syllable_count(lyrics: str | None, fallback: int = 8) -> int:
    """估算歌词音节数（用于决定音符数量）。"""
    if not lyrics:
        return fallback
    ph = [p for p in to_phonemes(lyrics) if p]
    return max(len(ph), 1)


def template_melody_midi(
    lyrics: str | None = None,
    tempo: float = 120.0,
    key: int | str | None = None,
    scale: str = "major",
    style: str = "default",
    out_path: str | None = None,
    seed: int = 42,
) -> str:
    """
    降级模板旋律：按歌词音节数生成简单旋律 MIDI。

    @param key: 调性（数字半音偏移 0-11，或调名 "C"/"Dm"/"Eb"）
    @param scale: major / minor / pentatonic / minor_penta
    @param style: default / calm / lively（影响跳进与时值）
    @return: 生成的 .mid 路径
    """
    rng = random.Random(seed)
    count = _syllable_count(lyrics)
    key_offset = _resolve_key(key)
    scale_table = _SCALES.get(scale, _SCALES["major"])
    s = _STYLES.get(style, _STYLES["default"])

    pm = pretty_midi.PrettyMIDI(initial_tempo=float(tempo))
    inst = pretty_midi.Instrument(program=0)
    beat = 60.0 / float(tempo)

    # 简单旋律走向：从根音出发，音阶内游走，句尾回落
    pitches = [key_offset + d for d in scale_table]
    note_idx = 0
    direction = 1
    for i in range(count):
        note_idx += rng.choice(s["jump"]) * direction
        note_idx = max(0, min(len(pitches) - 1, note_idx))
        if rng.random() < s["flip"]:
            direction *= -1
        pitch = pitches[note_idx]
        dur = beat * s["dur_mult"]
        # 句尾（最后 1-2 个音）回落收束
        if i >= count - 2:
            pitch = pitches[0]
            dur = beat * 2
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
    style: str = "default",
    tempo: float = 120.0,
    key: int | str | None = None,
    scale: str = "major",
    length_bars: int = 8,
    out_dir: str | None = None,
) -> dict:
    """
    MCP 工具 compose_song 的底层实现（降级模板路径）。

    @param style: default / calm / lively（旋律风格）
    @param key: 调性（数字 0-11 或调名 "C"/"Dm"/"Eb"）
    @param scale: major / minor / pentatonic / minor_penta
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
        key=key,
        scale=scale,
        style=style,
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
            "key": str(key) if key is not None else "C",
            "scale": scale,
            "style": style,
            "elapsed_sec": round(time.time() - t0, 2),
        }
    )
    return result


def _extract_lyrics_from_midi(midi_path: str) -> str:
    """从 MIDI 的 lyrics 事件提取歌词文本（无则返回空串）。"""
    pm = pretty_midi.PrettyMIDI(midi_path)
    try:
        events = pm.lyrics
    except AttributeError:
        return ""
    if not events:
        return ""
    return "".join(ev.text for ev in events if ev.text)


def _get_bpm(pm: pretty_midi.PrettyMIDI) -> float:
    """读取 MIDI 元数据 tempo（兜底 estimate_tempo）。"""
    try:
        _, tempos = pm.get_tempo_changes()
        if len(tempos):
            bpm = float(tempos[0])
            if 30 < bpm < 300:
                return bpm
    except Exception:
        pass
    est = pm.estimate_tempo()
    return est if 30 < est < 300 else 120.0


def _build_bridge(pm: pretty_midi.PrettyMIDI, end_time: float, bars: int, bpm: float) -> list:
    """生成 A→B 之间的桥接琶音（降级 infill：MIDI-GPT 未训练前的过渡段）。

    以 A 的最后一个音符为根音，做分解和弦上行（根音-三音-五音-高根音）。
    """
    # 收集 A 的主旋律音符作为根音来源
    root = 60
    for inst in pm.instruments:
        if not inst.is_drum and inst.notes:
            root = max(n.pitch for n in inst.notes) % 12 + 48  # 落在低音区
            break
    chord = [root, root + 4, root + 7, root + 12]
    beat = 60.0 / bpm
    dur = beat * 0.9
    notes = []
    t = end_time
    for bar in range(bars):
        for pitch in chord:
            notes.append(pretty_midi.Note(velocity=70, pitch=pitch, start=t, end=t + dur))
            t += beat
    return notes


def mix_songs(
    song_a_midi: str,
    song_b_midi: str,
    mode: str = "segment_ab",
    lyrics: str | None = None,
    bridge_bars: int = 2,
    out_dir: str | None = None,
) -> dict:
    """
    MCP 工具 mix_songs 的底层实现。

    @param mode:
        segment_ab       : A 全曲 + B 全曲拼接（默认）
        melody_a_lyrics_b: 用 A 的旋律 + 歌词（参数 lyrics 或从 B 的 MIDI 提取）生成
        infill_bridge    : A + 桥接琶音 + B（MIDI-GPT 未训练前的降级过渡段）
    @return: {status, midi_path, vsqx_path, mode, note_count, elapsed_sec}
    """
    import time

    from .midi2vpr import midi_to_vocaloid

    t0 = time.time()
    if not os.path.exists(song_a_midi) or not os.path.exists(song_b_midi):
        raise FileNotFoundError("song_a/song_b MIDI 文件不存在")
    if mode not in ("segment_ab", "melody_a_lyrics_b", "infill_bridge"):
        raise ValueError(f"未知模式: {mode}（支持 segment_ab / melody_a_lyrics_b / infill_bridge）")

    out_dir = out_dir or tempfile.gettempdir()
    os.makedirs(out_dir, exist_ok=True)
    out_mid = os.path.join(out_dir, f"mix_{int(t0)}.mid")

    pa = pretty_midi.PrettyMIDI(song_a_midi)
    pb = pretty_midi.PrettyMIDI(song_b_midi)
    bpm_a = _get_bpm(pa)
    bpm_b = _get_bpm(pb)
    offset_a = pa.get_end_time()

    if mode == "melody_a_lyrics_b":
        # A 的旋律轨单独成曲，歌词来自参数或 B 的 MIDI
        if not lyrics:
            lyrics = _extract_lyrics_from_midi(song_b_midi)
        pm = pretty_midi.PrettyMIDI(initial_tempo=bpm_a)
        for inst in pa.instruments:
            if not inst.is_drum and inst.notes:
                pm.instruments.append(inst)
                break
        pm.write(out_mid)
        result = midi_to_vocaloid(out_mid, lyrics=lyrics or None, out_dir=out_dir)
        result["lyrics_source"] = "param" if lyrics else "none"

    elif mode == "infill_bridge":
        # A + 桥接琶音 + B
        bridge_notes = _build_bridge(pa, offset_a, bridge_bars, bpm_a)
        bridge_end = (bridge_notes[-1].end if bridge_notes else offset_a) + 1.0
        pm = pretty_midi.PrettyMIDI(initial_tempo=bpm_a)
        for inst in pa.instruments:
            pm.instruments.append(inst)
        if bridge_notes:
            br = pretty_midi.Instrument(program=0, name="bridge")
            br.notes = bridge_notes
            pm.instruments.append(br)
        for inst in pb.instruments:
            new_inst = pretty_midi.Instrument(program=inst.program, is_drum=inst.is_drum, name=inst.name)
            for n in inst.notes:
                new_inst.notes.append(
                    pretty_midi.Note(
                        velocity=n.velocity,
                        pitch=n.pitch,
                        start=n.start + bridge_end,
                        end=n.end + bridge_end,
                    )
                )
            pm.instruments.append(new_inst)
        pm.write(out_mid)
        result = midi_to_vocaloid(out_mid, out_dir=out_dir)
        result["bridge_bars"] = bridge_bars

    else:  # segment_ab
        pm = pretty_midi.PrettyMIDI(initial_tempo=bpm_a)
        offset = offset_a + 1.0  # 1 秒间隔
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
