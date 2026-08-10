#!/usr/bin/env python3
"""
VOCALOID6 MCP 服务器入口（方案 A）。

注册工具：
  - compose_song       作曲编排（降级模板旋律，MIDI-GPT 后续接入）
  - midi_to_vocaloid   MIDI + 歌词 → .vsqx 工程文件
  - mix_songs          两曲混合改编（初版 segment_ab）
  - lyric_correct      日文歌词 → 音节/音素预检
  - open_in_vocaloid6  用系统关联程序打开工程文件
  - render_wav         方案 B 预留（未实现，返回提示）

启动：
  python server.py
（接入 MCP 客户端后由客户端拉起）
"""

import sys

from mcp.server.fastmcp import FastMCP

from v6mcp.compose import compose_song as _compose_song
from v6mcp.compose import mix_songs as _mix_songs
from v6mcp.lyrics import validate as _validate
from v6mcp.midi2vpr import list_voicebanks as _list_voicebanks
from v6mcp.midi2vpr import midi_to_vocaloid as _midi_to_vocaloid
from v6mcp.vocaloid6 import open_in_vocaloid6 as _open
from v6mcp.vocaloid6 import render_wav as _render

mcp = FastMCP("vocaloid6")


@mcp.tool()
def list_voicebanks() -> list:
    """列出本机已安装的 VOCALOID6 歌姬（声库）。

    返回每项：{comp_id, name, kind, lang, type, usable, hint}。
    kind="vvd" 为真实可用的声库（可直接写入工程，如 MIKU_V4X_Original_EVEC）；
    kind="vtb2" 为 V6 内置 AI 声库（HARUKA/AKITO/SARAH/ALLEN 等，compID 需在编辑器确认）。
    选歌姬时把 name（或 comp_id）传给 compose_song / midi_to_vocaloid 的 voice 参数。
    """
    return _list_voicebanks()


@mcp.tool()
def compose_song(
    lyrics: str = "",
    style: str = "default",
    tempo: float = 120.0,
    key: str = "C",
    scale: str = "major",
    length_bars: int = 8,
    out_dir: str = "",
    voice: str = "",
    emotion: str = "",
    structure: str = "",
) -> dict:
    """AI 作曲编排：歌词/想法 → 旋律 MIDI → VOCALOID6 工程文件（.vpr + .vsqx）。

    参数：
      lyrics      歌词（日文假名/片假名、或中文，中文自动转拼音）
      style       default / calm / lively（旋律风格）
      tempo       BPM（如 120）
      key         调性：C / Dm / Eb / F#m 或数字 0-11
      scale       major / minor / pentatonic / minor_penta
      voice       歌姬名或 compID（先用 list_voicebanks 查，如 "MIKU_V4X_Original_EVEC"）
      emotion     情感：happy 快乐 / sad 悲伤 / gentle 温柔 / passionate 激昂 /
                  rock 摇滚 / calm 平静（或中文别名），控制力度/开音/颤音/音域
      structure   歌曲结构：pop / simple / ballad（和弦进行 + 主歌/副歌/桥段）；留空用简单模板
      length_bars 小节数（仅无 structure 时参考）
    """
    return _compose_song(
        lyrics=lyrics or None,
        style=style,
        tempo=tempo,
        key=key or None,
        scale=scale,
        length_bars=length_bars,
        out_dir=out_dir or None,
        voice=voice or None,
        emotion=emotion or None,
        structure=structure or None,
    )


@mcp.tool()
def midi_to_vocaloid(
    midi_path: str,
    lyrics: str = "",
    song_name: str = "",
    tempo: float = 0.0,
    out_dir: str = "",
    voice: str = "",
    emotion: str = "",
) -> dict:
    """把 MIDI 转成 VOCALOID6 可打开的 .vpr 工程文件（音符 + 歌词音素）。

    参数：
      midi_path  输入 MIDI 文件路径
      lyrics     歌词（日文/中文，按音符对齐）
      voice      歌姬名或 compID（见 list_voicebanks）
      emotion    情感（happy/sad/gentle/passionate/rock/calm 或中文别名）
      tempo      覆盖 BPM（0 表示用 MIDI 内 tempo）
    """
    return _midi_to_vocaloid(
        midi_path=midi_path,
        lyrics=lyrics or None,
        song_name=song_name or None,
        tempo=tempo or None,
        out_dir=out_dir or None,
        voice=voice or None,
        emotion=emotion or None,
    )


@mcp.tool()
def mix_songs(
    song_a_midi: str,
    song_b_midi: str,
    mode: str = "segment_ab",
    out_dir: str = "",
) -> dict:
    """两曲混合改编：A 前半 + B 后半拼接（初版），输出混合 MIDI + .vsqx。"""
    return _mix_songs(
        song_a_midi=song_a_midi,
        song_b_midi=song_b_midi,
        mode=mode,
        out_dir=out_dir or None,
    )


@mcp.tool()
def lyric_correct(text: str, lang: str = "ja", return_phonemes: bool = True, custom_pinyin: dict = None) -> dict:
    """歌词预检：日文假名 → 音节/音素；中文 → 拼音。

    参数：
      text           歌词文本
      lang           ja=日文 / zh=中文（影响提示，不阻断转换）
      return_phonemes 是否返回 VOCALOID 音素序列
      custom_pinyin  可选：{汉字: 拼音} 补充内置字表未收录的字（如 {"魑":"chi"}）
    """
    v = _validate(text, custom_pinyin=custom_pinyin or None)
    result = {
        "ok": v["ok"],
        "syllable_count": v["syllable_count"],
        "syllables": v["syllables"],
        "unknown": v["unknown"],
        "lang_hint": "中文歌词会自动转拼音；未收录汉字请用 custom_pinyin 补充" if lang == "zh" else "",
    }
    if return_phonemes:
        from v6mcp.lyrics import to_vocaloid_phonemes

        result["phonemes"] = v["phonemes"]
        result["vocaloid_phonemes"] = to_vocaloid_phonemes(text, custom_pinyin=custom_pinyin or None)
    return result


@mcp.tool()
def open_in_vocaloid6(project_path: str) -> dict:
    """用系统关联程序打开 VOCALOID6 工程文件（.vsqx/.vpr）。"""
    return _open(project_path)


@mcp.tool()
def render_wav(project_path: str, output_wav: str = "", timeout_sec: int = 300) -> dict:
    """UI 自动化渲染 WAV：启动 VOCALOID6 打开工程并尝试导出音频。

    参数：
      project_path  .vpr/.vsqx 工程文件
      output_wav    输出 WAV 路径（缺省与工程同目录同名）
      timeout_sec   最大等待秒数
    任一步失败会返回明确错误与手动兜底步骤。
    """
    return _render(project_path, output_wav or None, timeout_sec)


def main() -> None:
    # 默认以 stdio 方式运行（MCP 客户端标准传输）
    print("VOCALOID6 MCP 服务器启动（stdio）...", file=sys.stderr, flush=True)
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
