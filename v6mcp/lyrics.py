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

def _hira_to_kata(ch: str) -> str:
    """平假名 → 同音片假名（用于补全片假名音素表）。"""
    code = ord(ch)
    if 0x3040 <= code <= 0x309F:
        return chr(code + 0x60)
    return ch


# 合并平/片假名查表
_KANA_MAP = {}
_KANA_MAP.update(_HIRA)
_KANA_MAP.update(_KATA)
# 拗音优先：两字组合先查（平/片假名都覆盖）
_YOON_MAP = {}
for k, v in _YOON.items():
    _YOON_MAP[k] = v
    _YOON_MAP["".join(_hira_to_kata(c) for c in k)] = v

# VOCALOID 音素表：假名 → 空格分隔的音素序列（合成引擎要求，非罗马音音节）
# 约定：う 系元音记作 M，ん 记作 N，し 记作 S i；参考 VOCALOID 标准音素表
_KANA_PHONEME = {
    "あ": "a", "い": "i", "う": "M", "え": "e", "お": "o",
    "か": "k a", "き": "k i", "く": "k M", "け": "k e", "こ": "k o",
    "さ": "s a", "し": "S i", "す": "s M", "せ": "s e", "そ": "s o",
    "た": "t a", "ち": "t i", "つ": "ts M", "て": "t e", "と": "t o",
    "な": "n a", "に": "n i", "ぬ": "n M", "ね": "n e", "の": "n o",
    "は": "h a", "ひ": "h i", "ふ": "f M", "へ": "h e", "ほ": "h o",
    "ま": "m a", "み": "m i", "む": "m M", "め": "m e", "も": "m o",
    "や": "y a", "ゆ": "y M", "よ": "y o",
    "ら": "r a", "り": "r i", "る": "r M", "れ": "r e", "ろ": "r o",
    "わ": "w a", "を": "o", "ん": "N",
    # 浊音
    "が": "g a", "ぎ": "g i", "ぐ": "g M", "げ": "g e", "ご": "g o",
    "ざ": "z a", "じ": "j i", "ず": "z M", "ぜ": "z e", "ぞ": "z o",
    "だ": "d a", "ぢ": "j i", "づ": "z M", "で": "d e", "ど": "d o",
    "ば": "b a", "び": "b i", "ぶ": "b M", "べ": "b e", "ぼ": "b o",
    # 半浊音
    "ぱ": "p a", "ぴ": "p i", "ぷ": "p M", "ぺ": "p e", "ぽ": "p o",
    # 拗音
    "きゃ": "k y a", "きゅ": "k y M", "きょ": "k y o",
    "しゃ": "S y a", "しゅ": "S y M", "しょ": "S y o",
    "ちゃ": "t y a", "ちゅ": "t y M", "ちょ": "t y o",
    "にゃ": "n y a", "にゅ": "n y M", "にょ": "n y o",
    "ひゃ": "h y a", "ひゅ": "h y M", "ひょ": "h y o",
    "みゃ": "m y a", "みゅ": "m y M", "みょ": "m y o",
    "りゃ": "r y a", "りゅ": "r y M", "りょ": "r y o",
    "ぎゃ": "g y a", "ぎゅ": "g y M", "ぎょ": "g y o",
    "じゃ": "j y a", "じゅ": "j y M", "じょ": "j y o",
    "びゃ": "b y a", "びゅ": "b y M", "びょ": "b y o",
    "ぴゃ": "p y a", "ぴゅ": "p y M", "ぴょ": "p y o",
}

# 为片假名补全同音音素（VOCALOID 音素不分平/片假名）
for _k, _v in list(_KANA_PHONEME.items()):
    if all(0x3040 <= ord(c) <= 0x309F for c in _k):
        _KANA_PHONEME["".join(_hira_to_kata(c) for c in _k)] = _v

# 长音符 ー：作为元音延长（VOCALOID 常用 "-"）
_KANA_PHONEME["ー"] = "-"
# 促音 っ/ッ：VOCALOID 中写作无声休止（常用 "R" 或省略），这里映射为 "-" 保持音长
_KANA_PHONEME["っ"] = "-"
_KANA_PHONEME["ッ"] = "-"

_KANA_RE = re.compile(r"[\u3040-\u309f\u30a0-\u30ff]")
_KANJI_RE = re.compile(r"[\u4e00-\u9fff]")

# ============ 常用汉字 → 拼音（VOCALOID 中文声库用拼音作 lyric） ============
# 覆盖常见歌词用字；未收录汉字会标记 unknown，可用 custom_pinyin 参数补充。
_ZH_PINYIN = {
    "我": "wo", "你": "ni", "他": "ta", "她": "ta", "它": "ta", "们": "men",
    "爱": "ai", "心": "xin", "月": "yue", "花": "hua", "夜": "ye", "风": "feng",
    "雨": "yu", "雪": "xue", "星": "xing", "光": "guang", "天": "tian", "地": "di",
    "海": "hai", "山": "shan", "水": "shui", "火": "huo", "云": "yun", "日": "ri",
    "春": "chun", "夏": "xia", "秋": "qiu", "冬": "dong", "年": "nian", "岁": "sui",
    "时": "shi", "间": "jian", "梦": "meng", "想": "xiang", "歌": "ge", "曲": "qu",
    "声": "sheng", "音": "yin", "乐": "yue", "路": "lu", "远": "yuan", "方": "fang",
    "在": "zai", "不": "bu", "是": "shi", "的": "de", "了": "le", "和": "he",
    "就": "jiu", "都": "dou", "会": "hui", "能": "neng", "要": "yao", "可": "ke",
    "来": "lai", "去": "qu", "走": "zou", "回": "hui", "看": "kan", "听": "ting",
    "说": "shuo", "笑": "xiao", "哭": "ku", "唱": "chang", "舞": "wu", "飞": "fei",
    "过": "guo", "有": "you", "没": "mei", "别": "bie", "再": "zai", "见": "jian",
    "之": "zhi", "中": "zhong", "上": "shang", "下": "xia", "前": "qian", "后": "hou",
    "生": "sheng", "死": "si", "命": "ming", "魂": "hun", "灵": "ling", "妖": "yao",
    "镇": "zhen", "城": "cheng", "古": "gu", "老": "lao", "小": "xiao", "大": "da",
    "白": "bai", "红": "hong", "黑": "hei", "青": "qing", "绿": "lv", "蓝": "lan",
    "金": "jin", "银": "yin", "剑": "jian", "刀": "dao", "书": "shu", "纸": "zhi",
    "灯": "deng", "门": "men", "窗": "chuang", "影": "ying", "光": "guang",
    "世": "shi", "界": "jie", "人": "ren", "情": "qing", "故": "gu", "事": "shi",
    "未": "wei", "来": "lai", "永": "yong", "恒": "heng", "万": "wan", "千": "qian",
    "等": "deng", "候": "hou", "望": "wang", "归": "gui", "相": "xiang", "遇": "yu",
    "别": "bie", "离": "li", "散": "san", "聚": "ju", "缘": "yuan", "分": "fen",
    "两": "liang", "个": "ge", "人": "ren", "双": "shuang", "眼": "yan", "泪": "lei",
    "手": "shou", "心": "xin", "中": "zhong", "空": "kong", "满": "man", "明": "ming",
    "暗": "an", "浅": "qian", "深": "shen", "长": "chang", "短": "duan",
    "照": "zhao", "亮": "liang", "夜": "ye", "美": "mei", "好": "hao",
    "行": "xing", "一": "yi", "是": "shi", "不": "bu", "在": "zai",
    "这": "zhe", "那": "na", "里": "li", "处": "chu", "谁": "shei",
    "何": "he", "无": "wu", "有": "you", "所": "suo", "以": "yi",
    "为": "wei", "因": "yin", "果": "guo", "如": "ru", "若": "ruo",
    "今": "jin", "昨": "zuo", "明": "ming", "当": "dang", "初": "chu",
    "愿": "yuan", "战": "zhan", "斗": "dou", "苍": "cang", "茫": "mang",
    "孤": "gu", "独": "du", "寂": "ji", "寞": "mo", "温": "wen",
    "暖": "nuan", "寒": "han", "冷": "leng", "家": "jia", "乡": "xiang",
    "望": "wang", "守": "shou", "护": "hu", "救": "jiu", "破": "po",
    "立": "li", "新": "xin", "旧": "jiu", "强": "qiang", "弱": "ruo",
    "真": "zhen", "假": "jia", "善": "shan", "恶": "e", "对": "dui",
    "错": "cuo", "难": "nan", "易": "yi", "苦": "ku", "甜": "tian",
    "万": "wan", "千": "qian", "百": "bai", "十": "shi", "数": "shu",
    "里": "li", "外": "wai", "东": "dong", "西": "xi", "南": "nan",
    "北": "bei", "从": "cong", "再": "zai", "还": "hai", "也": "ye",
    "都": "dou", "才": "cai", "又": "you", "只": "zhi", "像": "xiang",
}

# 声母表（用于拼音 → VOCALOID 音素拆分）
_ZH_INITIALS = ["zh", "ch", "sh", "b", "p", "m", "f", "d", "t", "n", "l", "g", "k",
                "h", "j", "q", "x", "r", "z", "c", "s", "y", "w"]


def _pinyin_to_phonemes(pinyin: str) -> str:
    """拼音 → VOCALOID 中文音素序列（声母逐字母 + 韵母逐字母）。

    例：wo → "w o"，zhong → "z h o n g"（与 V4C 中文声库兼容）。
    """
    p = pinyin.lower().strip()
    if not p:
        return "-"
    initial = ""
    for ini in _ZH_INITIALS:
        if p.startswith(ini):
            initial = ini
            p = p[len(ini):]
            break
    parts = list(initial) + list(p)
    return " ".join(parts) if parts else "-"


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


def _zh_pinyin(ch: str, custom: dict | None) -> str | None:
    """查汉字拼音：自定义读音优先，其次内置常用字表。"""
    if custom and ch in custom:
        return custom[ch]
    return _ZH_PINYIN.get(ch)


def to_syllables(text: str, custom_pinyin: dict | None = None) -> list:
    """
    把文本切成音节序列（每个假名/汉字一个音节）。
    - 假名：原样（含拗音组合）
    - 汉字：拼音（如 爱 → "ai"）
    - 其它字符（标点/英文）保留原样，便于人工校正
    """
    seq = _split_kana_sequence(text)
    syllables = []
    for ch in seq:
        if ch in _KANA_MAP or ch in _YOON_MAP:
            syllables.append(ch)
        elif ch.isspace():
            continue
        else:
            py = _zh_pinyin(ch, custom_pinyin)
            syllables.append(py if py else f"[{ch}]")
    return syllables


def to_phonemes(text: str, custom_pinyin: dict | None = None) -> list:
    """
    把文本转成 VOCALOID 音素表（罗马音/拼音列表）。
    每个可合成假名/汉字对应一个音素；无法识别的字符以 None 占位。
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
            py = _zh_pinyin(ch, custom_pinyin)
            phonemes.append(py if py else None)
    return phonemes


def to_vocaloid_phonemes(text: str, custom_pinyin: dict | None = None) -> list:
    """
    把文本转成 VOCALOID 合成引擎要求的「空格分隔音素序列」列表。

    与 to_phonemes（罗马音音节，如 sa）不同，VOCALOID 的 phoneme 字段
    必须是空格分隔的音素序列（如 さ → "s a"、く → "k M"），否则歌词不渲染。
    中文拼音按声母+韵母拆成音素（如 爱 ai → "a i"）。
    """
    seq = _split_kana_sequence(text)
    phonemes = []
    for ch in seq:
        if ch in _KANA_PHONEME:
            phonemes.append(_KANA_PHONEME[ch])
        elif ch.isspace():
            continue
        else:
            py = _zh_pinyin(ch, custom_pinyin)
            phonemes.append(_pinyin_to_phonemes(py) if py else None)
    return phonemes


def validate(text: str, custom_pinyin: dict | None = None) -> dict:
    """
    预检歌词可合成性。
    @return: {"ok": bool, "unknown": [字符...], "syllable_count": int, "phonemes": [...]}
    """
    phonemes = to_phonemes(text, custom_pinyin)
    unknown = [p for p in phonemes if p is None]
    syllables = to_syllables(text, custom_pinyin)
    return {
        "ok": len(unknown) == 0,
        "unknown": unknown,
        "syllable_count": len(syllables),
        "phonemes": phonemes,
        "syllables": syllables,
    }
