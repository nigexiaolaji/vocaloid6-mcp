"""
日文歌词 → VOCALOID 音节/音素转换。

VOCALOID 按「音节（假名）」合成，每个音符对应一个音节音素（如 か → ka）。
本模块提供：
  - to_syllables(text)   : 把日文文本切成假名字符序列（VOCALOID 音符填充用）
  - to_phonemes(text)    : 把假名序列转成 VOCALOID 音素表（罗马音）
  - validate(text)       : 预检歌词是否全部可合成（返回未知字符）

仅依赖 Python 标准库，无外部分词器（汉字读音需人工提供，见 README）。
"""

import re

# ============ 假名 → 罗马音映射表（基本音 + 浊音 + 拗音） ============
# 平假名
_HIRA = {
    "あ": "a", "い": "i", "う": "u", "え": "e", "お": "o",
    "か": "ka", "き": "ki", "く": "ku", "け": "ke", "こ": "ko",
    "さ": "sa", "し": "shi", "す": "su", "せ": "se", "そ": "so",
    "た": "ta", "ち": "chi", "つ": "tsu", "て": "te", "と": "to",
    "な": "na", "に": "ni", "ぬ": "nu", "ね": "ne", "の": "no",
    "は": "ha", "ひ": "hi", "ふ": "fu", "へ": "he", "ほ": "ho",
    "ま": "ma", "み": "mi", "む": "mu", "め": "me", "も": "mo",
    "や": "ya", "ゆ": "yu", "よ": "yo",
    "ら": "ra", "り": "ri", "る": "ru", "れ": "re", "ろ": "ro",
    "わ": "wa", "を": "o", "ん": "n",
    # 浊音
    "が": "ga", "ぎ": "gi", "ぐ": "gu", "げ": "ge", "ご": "go",
    "ざ": "za", "じ": "ji", "ず": "zu", "ぜ": "ze", "ぞ": "zo",
    "だ": "da", "ぢ": "ji", "づ": "zu", "で": "de", "ど": "do",
    "ば": "ba", "び": "bi", "ぶ": "bu", "べ": "be", "ぼ": "bo",
    # 半浊音
    "ぱ": "pa", "ぴ": "pi", "ぷ": "pu", "ぺ": "pe", "ぽ": "po",
    # 小写（拗音用，独立出现时按基础音处理）
    "ぁ": "a", "ぃ": "i", "ぅ": "u", "ぇ": "e", "ぉ": "o",
    "ゃ": "ya", "ゅ": "yu", "ょ": "yo",
    "っ": "tsu",  # 促音兜底
}

# 片假名（同音映射）
_KATA = {
    "ア": "a", "イ": "i", "ウ": "u", "エ": "e", "オ": "o",
    "カ": "ka", "キ": "ki", "ク": "ku", "ケ": "ke", "コ": "ko",
    "サ": "sa", "シ": "shi", "ス": "su", "セ": "se", "ソ": "so",
    "タ": "ta", "チ": "chi", "ツ": "tsu", "テ": "te", "ト": "to",
    "ナ": "na", "ニ": "ni", "ヌ": "nu", "ネ": "ne", "ノ": "no",
    "ハ": "ha", "ヒ": "hi", "フ": "fu", "ヘ": "he", "ホ": "ho",
    "マ": "ma", "ミ": "mi", "ム": "mu", "メ": "me", "モ": "mo",
    "ヤ": "ya", "ユ": "yu", "ヨ": "yo",
    "ラ": "ra", "リ": "ri", "ル": "ru", "レ": "re", "ロ": "ro",
    "ワ": "wa", "ヲ": "o", "ン": "n",
    "ガ": "ga", "ギ": "gi", "グ": "gu", "ゲ": "ge", "ゴ": "go",
    "ザ": "za", "ジ": "ji", "ズ": "zu", "ゼ": "ze", "ゾ": "zo",
    "ダ": "da", "ヂ": "ji", "ヅ": "zu", "デ": "de", "ド": "do",
    "バ": "ba", "ビ": "bi", "ブ": "bu", "ベ": "be", "ボ": "bo",
    "パ": "pa", "ピ": "pi", "プ": "pu", "ペ": "pe", "ポ": "po",
    "ァ": "a", "ィ": "i", "ゥ": "u", "ェ": "e", "ォ": "o",
    "ャ": "ya", "ュ": "yu", "ョ": "yo",
    "ッ": "tsu",
    "ー": "-",  # 长音符：VOCALOID 中常写作 "-"
}

# 拗音组合表：小假名跟在基础假名后合并（如 きゃ → kya）
_YOON = {
    "きゃ": "kya", "きゅ": "kyu", "きょ": "kyo",
    "しゃ": "sha", "しゅ": "shu", "しょ": "sho",
    "ちゃ": "cha", "ちゅ": "chu", "ちょ": "cho",
    "にゃ": "nya", "にゅ": "nyu", "にょ": "nyo",
    "ひゃ": "hya", "ひゅ": "hyu", "ひょ": "hyo",
    "みゃ": "mya", "みゅ": "myu", "みょ": "myo",
    "りゃ": "rya", "りゅ": "ryu", "りょ": "ryo",
    "ぎゃ": "gya", "ぎゅ": "gyu", "ぎょ": "gyo",
    "じゃ": "ja", "じゅ": "ju", "じょ": "jo",
    "びゃ": "bya", "びゅ": "byu", "びょ": "byo",
    "ぴゃ": "pya", "ぴゅ": "pyu", "ぴょ": "pyo",
    "しゃ": "sha", "しゅ": "shu", "しょ": "sho",
}

# 合并平/片假名查表
_KANA_MAP = {}
_KANA_MAP.update(_HIRA)
_KANA_MAP.update(_KATA)
# 拗音优先：两字组合先查
_YOON_MAP = {}
for k, v in _YOON.items():
    _YOON_MAP[k] = v
    _YOON_MAP[k.upper() if False else k] = v  # 片假名拗音同样适用（假名本身区分）

_KANA_RE = re.compile(r"[\u3040-\u309f\u30a0-\u30ff]")
_KANJI_RE = re.compile(r"[\u4e00-\u9fff]")


def _split_kana_sequence(text: str) -> list:
    """把文本切成「假名字符 / 其它字符」的序列，优先合并拗音两字组合。"""
    chars = list(text)
    out = []
    i = 0
    while i < len(chars):
        # 尝试两字拗音组合
        if i + 1 < len(chars):
            pair = chars[i] + chars[i + 1]
            if pair in _YOON_MAP:
                out.append(pair)
                i += 2
                continue
        out.append(chars[i])
        i += 1
    return out


def to_syllables(text: str) -> list:
    """
    把日文文本切成音节序列（每个假名/拗音组合一个音节）。
    非假名字符（汉字/英文/标点）原样保留，便于后续人工校正。
    """
    seq = _split_kana_sequence(text)
    syllables = []
    for ch in seq:
        if ch in _KANA_MAP or ch in _YOON_MAP:
            syllables.append(ch)
        elif ch.isspace():
            continue
        else:
            # 汉字/其它：原样保留并标记
            syllables.append(f"[{ch}]")
    return syllables


def to_phonemes(text: str) -> list:
    """
    把日文文本转成 VOCALOID 音素表（罗马音列表）。
    每个可合成假名对应一个音素；汉字等不可合成字符以 None 占位。
    """
    seq = _split_kana_sequence(text)
    phonemes = []
    for ch in seq:
        if ch in _YOON_MAP:
            phonemes.append(_YOON_MAP[ch])
        elif ch in _KANA_MAP:
            phonemes.append(_KANA_MAP[ch])
        elif ch.isspace():
            continue
        else:
            phonemes.append(None)  # 汉字等，需人工读音
    return phonemes


def validate(text: str) -> dict:
    """
    预检歌词可合成性。
    @return: {"ok": bool, "unknown": [字符...], "syllable_count": int, "phonemes": [...]}
    """
    phonemes = to_phonemes(text)
    unknown = [p for p in phonemes if p is None]
    syllables = to_syllables(text)
    return {
        "ok": len(unknown) == 0,
        "unknown": unknown,
        "syllable_count": len(syllables),
        "phonemes": phonemes,
        "syllables": syllables,
    }
