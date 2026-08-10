"""
情感 → VOCALOID 表现力参数映射（emotion → exp/velocity/vibrato/controllers）。

VOCALOID6 的表达力通过两类通道实现：
  1. 音符级：velocity（力度/辅音长短）、exp.opening（开音度）、vibrato（颤音）
  2. Part 级 controllers：DYN（Dynamics 力度变化）、BRI（Brightness 亮度）、
     CLE（Clearness 清晰度）、GEN（Gender 音色）、OPE（Opening 开音度）、
     PIT（Pitch Bend 音高弯音）

情感表把"快乐/悲伤/温柔/激昂/摇滚/平静"等映射到这些参数的合理取值，
AI 只需传情感名（或组合），无需懂底层参数。
"""

# 情感 → 参数组合
# velocity:  音符力度 1-127（越大辅音越短促、发音越有力）
# opening:   开音度 0-127（越大嘴型越开、音量越大）
# vibrato_type:  0=无 1=标准 2=柔和 3=强烈（V6 支持的类型）
# vibrato_dur:   颤音长度（tick，0=无）
# controllers:   Part 级曲线事件 {name: value}，写成一个事件从 0 到末尾
_EMOTIONS: dict = {
    "happy": {  # 快乐：明亮、轻快、力度足
        "velocity": 105, "opening": 100,
        "vibrato_type": 2, "vibrato_dur": 90,
        "controllers": {"DYN": 96, "BRI": 110, "CLE": 100, "GEN": 64, "OPE": 90},
    },
    "sad": {  # 悲伤：暗、弱、缓
        "velocity": 60, "opening": 40,
        "vibrato_type": 1, "vibrato_dur": 150,
        "controllers": {"DYN": 30, "BRI": 30, "CLE": 60, "GEN": 55, "OPE": 30},
    },
    "gentle": {  # 温柔：柔和、中音区、气声感
        "velocity": 72, "opening": 55,
        "vibrato_type": 2, "vibrato_dur": 120,
        "controllers": {"DYN": 55, "BRI": 60, "CLE": 75, "GEN": 60, "OPE": 50},
    },
    "passionate": {  # 激昂/热情：强、亮、颤音明显
        "velocity": 118, "opening": 115,
        "vibrato_type": 3, "vibrato_dur": 120,
        "controllers": {"DYN": 120, "BRI": 118, "CLE": 95, "GEN": 68, "OPE": 110},
    },
    "rock": {  # 摇滚：重、锐、开音大
        "velocity": 122, "opening": 120,
        "vibrato_type": 3, "vibrato_dur": 60,
        "controllers": {"DYN": 127, "BRI": 120, "CLE": 110, "GEN": 45, "OPE": 125},
    },
    "calm": {  # 平静：均匀、轻、无颤音
        "velocity": 68, "opening": 50,
        "vibrato_type": 0, "vibrato_dur": 0,
        "controllers": {"DYN": 50, "BRI": 55, "CLE": 70, "GEN": 60, "OPE": 45},
    },
    "default": {  # 默认（缺省）
        "velocity": 90, "opening": 80,
        "vibrato_type": 1, "vibrato_dur": 80,
        "controllers": {"DYN": 75, "BRI": 75, "CLE": 80, "GEN": 64, "OPE": 70},
    },
}

# 支持的控制器名（V6 标准声库控制参数）
_CONTROLLER_NAMES = ("DYN", "BRI", "CLE", "GEN", "OPE")

# 情感别名（中文/英文）
_ALIASES = {
    "happy": "快乐", "sad": "悲伤", "gentle": "温柔", "passionate": "激昂",
    "rock": "摇滚", "calm": "平静", "default": "默认",
}


def resolve_emotion(emotion: str | None) -> str:
    """把情感名解析为表内 key；支持中文别名，未知值回退 default。"""
    if not emotion:
        return "default"
    e = str(emotion).strip().lower()
    if e in _EMOTIONS:
        return e
    for key, alias in _ALIASES.items():
        if e == alias or e == alias.lower():
            return key
    return "default"


def emotion_params(emotion: str | None) -> dict:
    """返回情感对应的参数组合 dict（已解析 key）。"""
    key = resolve_emotion(emotion)
    return dict(_EMOTIONS[key], _key=key, _label=_ALIASES[key])


def apply_to_note(emotion: str | None, note_velocity: int, base_opening: int = 80) -> dict:
    """计算单个音符的表现力参数：velocity / opening / vibrato。

    @return: {"velocity": int, "opening": int, "vibrato_type": int, "vibrato_dur": int}
    """
    p = emotion_params(emotion)
    return {
        "velocity": p["velocity"],
        "opening": base_opening if emotion is None else p["opening"],
        "vibrato_type": p["vibrato_type"],
        "vibrato_dur": p["vibrato_dur"],
    }


def build_controllers(emotion: str | None, total_ticks: int) -> list:
    """生成 Part 级 controllers（每个参数一个事件，从 0 延伸到曲尾）。

    @return: [{"name": str, "events": [{"pos": 0, "value": int}]}, ...]
    """
    p = emotion_params(emotion)
    out = []
    for name in _CONTROLLER_NAMES:
        if name in p["controllers"]:
            out.append(
                {
                    "name": name,
                    "events": [{"pos": 0, "value": p["controllers"][name]}],
                }
            )
    return out


def describe(emotion: str | None) -> str:
    """给 AI/用户看的说明（不暴露底层参数细节）。"""
    p = emotion_params(emotion)
    return f"情感「{p['_label']}」（{p['_key']}）：力度 {p['velocity']}，开音 {p['opening']}，颤音类型 {p['vibrato_type']}"
