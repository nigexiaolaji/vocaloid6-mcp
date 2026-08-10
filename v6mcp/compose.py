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

# 和弦进行（半音偏移，相对主音；大调）
#   I=V 级数：I=0, ii=2, iii=4, IV=5, V=7, vi=9, vii=11
_CHORD_PROGRESSIONS_MAJOR = {
    "I-V-vi-IV":     [0, 7, 9, 5],    # 最流行：C-G-Am-F
    "vi-IV-I-V":     [9, 5, 0, 7],    # 卡农式：Am-F-C-G
    "I-vi-IV-V":     [0, 9, 5, 7],    # 50s 进行：C-Am-F-G
    "I-IV-V":        [0, 5, 7],       # 蓝调摇滚：C-F-G
    "I-V-IV":        [0, 7, 5],       # 简单明亮：C-G-F
    "vi-V-IV":       [9, 7, 5],       # 小调感：Am-G-F
}

# 小调进行（自然小调：i=0, III=3, iv=5, v=7, VI=8, VII=10）
_CHORD_PROGRESSIONS_MINOR = {
    "i-VI-III-VII":  [0, 8, 3, 10],   # 经典小调：Am-F-C-G
    "i-iv-VII-VI":   [0, 5, 10, 8],   # 和声感：Am-Dm-G-F
    "i-VII-VI-V":    [0, 10, 8, 7],   # 下行：Am-G-F-E
    "i-iv-v":        [0, 5, 7],       # 朴素：Am-Dm-Em
}

# 三和弦音（半音，0=根音）
_TRIADS_MAJOR = (0, 4, 7)    # 大三和弦
_TRIADS_MINOR = (0, 3, 7)    # 小三和弦
# 和弦性质：进行里每个根音对应的和弦类型（大/小）
# 大调音级：I 大 ii 小 iii 小 IV 大 V 大 vi 小 vii 减（按 vi 小处理）
_MAJOR_DEGREE_TYPE = {0: "M", 2: "m", 4: "m", 5: "M", 7: "M", 9: "m", 11: "m"}
# 小调音级：i 小 III 大 iv 小 v 小(和声大) VI 大 VII 大
_MINOR_DEGREE_TYPE = {0: "m", 3: "M", 5: "m", 7: "m", 8: "M", 10: "M"}

# 歌曲结构模板：段序列（每段小节数，和弦进行 key）
#   verse 主歌（平稳）、chorus 副歌（明亮/高潮）、bridge 桥段（对比）、intro/outro
_STRUCTURES = {
    "pop": [
        ("verse", 4, "I-V-vi-IV"),
        ("chorus", 4, "vi-IV-I-V"),
        ("verse", 4, "I-V-vi-IV"),
        ("chorus", 4, "vi-IV-I-V"),
        ("bridge", 2, "vi-IV-I-V"),
        ("chorus", 4, "I-V-vi-IV"),
    ],
    "simple": [
        ("verse", 4, "I-V-vi-IV"),
        ("chorus", 4, "I-V-vi-IV"),
        ("verse", 4, "I-V-vi-IV"),
        ("chorus", 4, "I-V-vi-IV"),
    ],
    "ballad": [
        ("intro", 2, "vi-IV-I-V"),
        ("verse", 4, "I-vi-IV-V"),
        ("chorus", 4, "vi-IV-I-V"),
        ("verse", 4, "I-vi-IV-V"),
        ("bridge", 2, "IV-V-vi"),
        ("chorus", 4, "vi-IV-I-V"),
        ("outro", 2, "I-V-vi-IV"),
    ],
}

# 每段情感/力度基调（段名 → 力度基数偏移）
_SECTION_CFG = {
    "intro":  {"vel": -8, "base": -2, "dur": 1.6},
    "verse":  {"vel": 0,  "base": 0,  "dur": 1.0},
    "chorus": {"vel": 10, "base": 4,  "dur": 0.8},
    "bridge": {"vel": 4,  "base": -4, "dur": 1.3},
    "outro":  {"vel": -5, "base": -3, "dur": 1.8},
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


def _chord_pool(key_offset: int, scale: str, chord_root: int, chord_type: str) -> list:
    """返回当前和弦的可用旋律音（半音 pitch，含高八度）。"""
    base = 60 + key_offset + chord_root
    triad = _TRIADS_MAJOR if chord_type == "M" else _TRIADS_MINOR
    # 和弦音 + 高八度根音，落在一个八度内，便于旋律选音
    pool = [base + t for t in triad]
    pool.append(base + 12)
    return pool


def _section_chords(section: str, scale: str, prog_key: str, key_offset: int):
    """把某段的和弦进行展开成逐小节 (根音半音, 和弦类型) 列表。"""
    if scale == "minor" or scale == "minor_penta":
        prog = _CHORD_PROGRESSIONS_MINOR.get(prog_key, _CHORD_PROGRESSIONS_MINOR["i-VI-III-VII"])
        degree_type = _MINOR_DEGREE_TYPE
    else:
        prog = _CHORD_PROGRESSIONS_MAJOR.get(prog_key, _CHORD_PROGRESSIONS_MAJOR["I-V-vi-IV"])
        degree_type = _MAJOR_DEGREE_TYPE
    chords = []
    for root in prog:
        chords.append((root, degree_type.get(root, "M")))
    return chords


def structured_melody_midi(
    lyrics: str | None = None,
    tempo: float = 120.0,
    key: int | str | None = None,
    scale: str = "major",
    style: str = "default",
    structure: str = "pop",
    out_path: str | None = None,
    seed: int = 42,
    emotion: str | None = None,
) -> str:
    """
    结构化旋律：和弦进行驱动 + 歌曲结构（verse/chorus/bridge）+ 力度起伏。

    @param structure: pop / simple / ballad（歌曲结构模板）
    @param emotion: 情感（影响音域/音长/力度基调）
    @return: 生成的 .mid 路径
    """
    from .emotion import emotion_params

    rng = random.Random(seed)
    key_offset = _resolve_key(key)
    s = _STYLES.get(style, _STYLES["default"])
    ep = emotion_params(emotion)

    sections = _STRUCTURES.get(structure, _STRUCTURES["pop"])
    total_bars = sum(bars for _, bars, _ in sections)

    # 音符数量 = 歌词音节数（歌曲长度由歌词决定，而不是被结构小节数撑长）
    syll = _syllable_count(lyrics, fallback=8)
    count = max(syll, 1)

    beat = 60.0 / float(tempo)
    pm = pretty_midi.PrettyMIDI(initial_tempo=float(tempo))
    inst = pretty_midi.Instrument(program=0)

    # 情感 → 旋律倾向（与 template 一致，供各段叠加）
    emotion_registry = {
        "happy":      {"base": 65, "vel": 100, "dur": 0.8, "jump": [-2, -1, 0, 1, 2]},
        "sad":        {"base": 55, "vel": 62,  "dur": 1.6, "jump": [-1, 0, 1]},
        "gentle":     {"base": 58, "vel": 74,  "dur": 1.4, "jump": [-1, 0, 1]},
        "passionate": {"base": 67, "vel": 115, "dur": 0.7, "jump": [-2, -1, 0, 1, 2, 3]},
        "rock":       {"base": 62, "vel": 122, "dur": 0.6, "jump": [-3, -2, 1, 2, 3]},
        "calm":       {"base": 57, "vel": 68,  "dur": 1.8, "jump": [-1, 0, 1]},
        "default":    {"base": 60, "vel": 90,  "dur": 1.0, "jump": [-1, 0, 1]},
    }
    e_cfg = emotion_registry.get(ep["_key"], emotion_registry["default"])

    # 预建「小节索引 → (段配置, 和弦)」映射，供音符按时间定位
    bar_chords = []  # (sec_name, chord_root, chord_type, scfg)
    for sec_name, bars, prog_key in sections:
        chords = _section_chords(sec_name, scale, prog_key, key_offset)
        scfg = _SECTION_CFG.get(sec_name, {"vel": 0, "base": 0, "dur": 1.0})
        for _b in range(bars):
            chord_root, chord_type = chords[_b % len(chords)]
            bar_chords.append((sec_name, chord_root, chord_type, scfg))

    # 每音节 1 拍（情感/风格可微调 0.5~2 拍），音符首尾相接 → 演唱连贯、不拖长
    dur_mult = e_cfg["dur"] if emotion else s["dur_mult"]
    note_beats = max(0.5, min(2.0, dur_mult))
    note_len = beat * note_beats  # 每音符时长（秒）
    prev_pitch = None
    for i in range(count):
        t = i * note_len
        bar_idx = int(t / (4 * beat)) % len(bar_chords)
        sec_name, chord_root, chord_type, scfg = bar_chords[bar_idx]
        pool = _chord_pool(key_offset, scale, chord_root, chord_type)
        # 段基调 + 情感基准
        base_pitch = e_cfg["base"] + scfg["base"]
        vel = max(20, min(127, e_cfg["vel"] + scfg["vel"]))
        # 选音：优先和弦音（概率 70%），否则音阶经过音；句尾回落
        if i >= count - 2:
            pitch = pool[0]  # 落回和弦根音
        elif rng.random() < 0.7:
            pitch = rng.choice(pool)
        else:
            step = rng.choice(s["jump"])
            pitch = prev_pitch + step if prev_pitch is not None else pool[rng.randrange(len(pool))]
        pitch = max(48, min(84, pitch))
        # 小节强拍（每小节第 1 拍）力度略高 → 起伏感
        beat_vel = vel + (8 if int(t / beat) % 4 == 0 else -6)
        beat_vel = max(20, min(127, beat_vel))
        inst.notes.append(
            pretty_midi.Note(
                velocity=beat_vel,
                pitch=pitch,
                start=t,
                end=t + note_len,
            )
        )
        prev_pitch = pitch

    pm.instruments.append(inst)
    if not out_path:
        out_path = os.path.join(tempfile.gettempdir(), "structured_melody.mid")
    pm.write(out_path)
    return out_path


def template_melody_midi(
    lyrics: str | None = None,
    tempo: float = 120.0,
    key: int | str | None = None,
    scale: str = "major",
    style: str = "default",
    out_path: str | None = None,
    seed: int = 42,
    emotion: str | None = None,
    structure: str | None = None,
) -> str:
    """
    旋律生成（兼容入口）：structure 给定则走和弦驱动结构生成，否则用简单模板。

    @param structure: pop / simple / ballad / None（None=简单模板）
    """
    if structure:
        return structured_melody_midi(
            lyrics=lyrics, tempo=tempo, key=key, scale=scale, style=style,
            structure=structure, out_path=out_path, seed=seed, emotion=emotion,
        )
    from .emotion import emotion_params

    rng = random.Random(seed)
    count = _syllable_count(lyrics)
    key_offset = _resolve_key(key)
    scale_table = _SCALES.get(scale, _SCALES["major"])
    s = _STYLES.get(style, _STYLES["default"])
    ep = emotion_params(emotion)

    pm = pretty_midi.PrettyMIDI(initial_tempo=float(tempo))
    inst = pretty_midi.Instrument(program=0)
    beat = 60.0 / float(tempo)

    # 情感 → 旋律倾向：
    #   快乐/激昂/摇滚：基准音域高、音长短、力度大、跳进大
    #   悲伤/温柔/平静：基准音域低、音长长、力度小、跳进小
    emotion_registry = {
        "happy":      {"base": 65, "vel": 100, "dur": 0.8, "jump": [-2, -1, 0, 1, 2]},
        "sad":        {"base": 55, "vel": 62,  "dur": 1.6, "jump": [-1, 0, 1]},
        "gentle":     {"base": 58, "vel": 74,  "dur": 1.4, "jump": [-1, 0, 1]},
        "passionate": {"base": 67, "vel": 115, "dur": 0.7, "jump": [-2, -1, 0, 1, 2, 3]},
        "rock":       {"base": 62, "vel": 122, "dur": 0.6, "jump": [-3, -2, 1, 2, 3]},
        "calm":       {"base": 57, "vel": 68,  "dur": 1.8, "jump": [-1, 0, 1]},
        "default":    {"base": 60, "vel": 90,  "dur": 1.0, "jump": [-1, 0, 1]},
    }
    e_cfg = emotion_registry.get(ep["_key"], emotion_registry["default"])
    base_pitch = e_cfg["base"] + key_offset
    jumps = e_cfg["jump"] if emotion else s["jump"]
    dur_mult = e_cfg["dur"] if emotion else s["dur_mult"]

    # 简单旋律走向：从根音出发，音阶内游走，句尾回落
    pitches = [base_pitch + d for d in scale_table]
    note_idx = 0
    direction = 1
    for i in range(count):
        note_idx += rng.choice(jumps) * direction
        note_idx = max(0, min(len(pitches) - 1, note_idx))
        if rng.random() < s["flip"]:
            direction *= -1
        pitch = pitches[note_idx]
        dur = beat * dur_mult
        # 句尾（最后 1-2 个音）回落收束
        if i >= count - 2:
            pitch = pitches[0]
            dur = beat * 2
        inst.notes.append(
            pretty_midi.Note(
                velocity=e_cfg["vel"],
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


# MIDI-GPT 微调权重默认路径（可用环境变量 MIDIGPT_CHECKPOINT 覆盖）
_DEFAULT_MIDIGPT_CKPT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "checkpoints", "midigpt", "run_001", "model_final.safetensors",
)


def _midigpt_checkpoint() -> str | None:
    """返回可用的 MIDI-GPT 微调权重路径（不存在返回 None）。"""
    p = os.environ.get("MIDIGPT_CHECKPOINT") or _DEFAULT_MIDIGPT_CKPT
    return p if os.path.isfile(p) else None


def midigpt_melody_midi(
    lyrics: str | None = None,
    out_path: str | None = None,
    seed: int = 42,
    checkpoint: str | None = None,
    bars: int = 4,
    tracks: int = 1,
) -> str:
    """
    用微调的 MIDI-GPT 生成旋律 MIDI（scratch 模式，AI 原创旋律）。

    @param bars: 生成小节数（按歌词音节数自动估算，最少 4 小节保证质量）
    @param tracks: 轨道数（默认 1 轨主旋律，后续可扩展多轨）
    @return: 生成的 .mid 路径
    """
    import json  # noqa: F401

    from midigpt import Bar, Score, Track
    from midigpt.inference import (
        GenerationRequest,
        InferenceConfig,
        InferenceEngine,
        TrackPrompt,
    )

    ckpt = checkpoint or _midigpt_checkpoint()
    if not ckpt:
        raise FileNotFoundError(
            "未找到 MIDI-GPT 微调权重（checkpoints/midigpt/run_001/model_final.safetensors），"
            "请先回传权重或用 MIDIGPT_CHECKPOINT 指定路径"
        )

    syll = _syllable_count(lyrics, fallback=bars * 4)
    bars = max(4, (syll + 3) // 4)  # 每小节约 4 音节，最少 4 小节

    engine = InferenceEngine.from_checkpoint(ckpt)
    score = Score(
        tracks=[
            Track(bars=[Bar() for _ in range(bars)], instrument=0, track_type="melodic")
            for _ in range(tracks)
        ]
    )
    request = GenerationRequest(
        tracks=[
            TrackPrompt(id=i, bars=list(range(bars)), autoregressive=True)
            for i in range(tracks)
        ],
        config=InferenceConfig(
            temperature=1.0,
            top_p=0.95,
            model_dim=bars,
            seed=seed,
        ),
    )
    result = engine.session(score, request).run()
    if not out_path:
        out_path = os.path.join(tempfile.gettempdir(), "midigpt_melody.mid")
    result.to_midi(str(out_path))
    return out_path


def compose_song(
    lyrics: str | None = None,
    style: str = "default",
    tempo: float = 120.0,
    key: int | str | None = None,
    scale: str = "major",
    length_bars: int = 8,
    out_dir: str | None = None,
    voice: str | None = None,
    emotion: str | None = None,
    structure: str | None = None,
    engine: str = "auto",
) -> dict:
    """
    MCP 工具 compose_song 的底层实现。

    @param style: default / calm / lively（旋律风格，仅 template 引擎使用）
    @param key: 调性（数字 0-11 或调名 "C"/"Dm"/"Eb"）
    @param scale: major / minor / pentatonic / minor_penta
    @param voice: 歌姬名或 compID（如 "MIKU_V4X_Original_EVEC"）
    @param emotion: 情感（happy/sad/gentle/passionate/rock/calm 或中文别名）
    @param structure: pop / simple / ballad / None（和弦进行 + 主歌/副歌/桥段结构，仅 template 引擎）
    @param engine: auto=有权重用 midigpt 否则 template；midigpt=强制；template=强制
    @return: {status, midi_path, vsqx_path, note_count, tempo, engine, elapsed_sec}
    """
    import time

    from .midi2vpr import midi_to_vocaloid

    t0 = time.time()
    out_dir = out_dir or tempfile.gettempdir()
    os.makedirs(out_dir, exist_ok=True)

    song_name = f"composed_{int(t0)}"
    out_mid = os.path.join(out_dir, song_name + ".mid")

    # 引擎选择：auto → 权重存在用 midigpt；显式 midigpt → 强制；template → 强制
    ckpt = _midigpt_checkpoint()
    use_midigpt = (engine == "midigpt") or (engine == "auto" and ckpt is not None)
    engine_used = "template"

    if use_midigpt:
        try:
            midi_path = midigpt_melody_midi(
                lyrics=lyrics,
                out_path=out_mid,
                seed=int(t0) % (2**31),
            )
            engine_used = "midigpt"
        except Exception as e:
            # midigpt 失败降级 template，保证链路不中断
            print(f"[compose_song] midigpt 引擎失败，降级 template: {e}", flush=True)
            midi_path = template_melody_midi(
                lyrics=lyrics,
                tempo=tempo,
                key=key,
                scale=scale,
                style=style,
                out_path=out_mid,
                emotion=emotion,
                structure=structure,
            )
    else:
        midi_path = template_melody_midi(
            lyrics=lyrics,
            tempo=tempo,
            key=key,
            scale=scale,
            style=style,
            out_path=out_mid,
            emotion=emotion,
            structure=structure,
        )

    result = midi_to_vocaloid(
        midi_path,
        lyrics=lyrics,
        song_name=song_name,
        tempo=tempo,
        out_dir=out_dir,
        voice=voice,
        emotion=emotion,
    )
    result.update(
        {
            "status": "ok",
            "midi_path": midi_path,
            "engine": engine_used,
            "engine_requested": engine,
            "key": str(key) if key is not None else "C",
            "scale": scale,
            "style": style,
            "structure": structure or "none",
            "voice": voice or result.get("voice", ""),
            "emotion": result.get("emotion", ""),
            "emotion_label": result.get("emotion_label", ""),
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
