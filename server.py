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
from v6mcp.midi2vpr import midi_to_vocaloid as _midi_to_vocaloid
from v6mcp.vocaloid6 import open_in_vocaloid6 as _open
from v6mcp.vocaloid6 import render_wav as _render

mcp = FastMCP("vocaloid6")


@mcp.tool()
def compose_song(
    lyrics: str = "",
    style: str = "default",
    tempo: float = 120.0,
    key: str = "C",
    scale: str = "major",
    length_bars: int = 8,
    out_dir: str = "",
) -> dict:
    """AI 作曲编排：输入歌词/想法，生成旋律 MIDI 并转为 VOCALOID6 工程文件。
    参数：style=default/calm/lively，key=调名(C/Dm/Eb)或数字，scale=major/minor/pentatonic。
    当前使用降级模板旋律（MIDI-GPT 训练完成后自动切换引擎）。
    """
    return _compose_song(
        lyrics=lyrics or None,
        style=style,
        tempo=tempo,
        key=key or None,
        scale=scale,
        length_bars=length_bars,
        out_dir=out_dir or None,
    )


@mcp.tool()
def midi_to_vocaloid(
    midi_path: str,
    lyrics: str = "",
    song_name: str = "",
    tempo: float = 0.0,
    out_dir: str = "",
) -> dict:
    """把 MIDI 转成 VOCALOID6 可打开的 .vsqx 工程文件（音符 + 歌词音素）。"""
    return _midi_to_vocaloid(
        midi_path=midi_path,
        lyrics=lyrics or None,
        song_name=song_name or None,
        tempo=tempo or None,
        out_dir=out_dir or None,
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
def lyric_correct(text: str, lang: str = "ja", return_phonemes: bool = True) -> dict:
    """日文歌词 → 音节/音素预检（VOCALOID 合成输入）。"""
    v = _validate(text)
    result = {
        "ok": v["ok"],
        "syllable_count": v["syllable_count"],
        "syllables": v["syllables"],
        "unknown": v["unknown"],
    }
    if return_phonemes:
        result["phonemes"] = v["phonemes"]
    return result


@mcp.tool()
def open_in_vocaloid6(project_path: str) -> dict:
    """用系统关联程序打开 VOCALOID6 工程文件（.vsqx/.vpr）。"""
    return _open(project_path)


@mcp.tool()
def render_wav(project_path: str, output_wav: str = "", timeout_sec: int = 300) -> dict:
    """渲染 WAV（方案 B 预留，当前返回手动操作提示）。"""
    return _render(project_path, output_wav or None, timeout_sec)


def main() -> None:
    # 默认以 stdio 方式运行（MCP 客户端标准传输）
    print("VOCALOID6 MCP 服务器启动（stdio）...", file=sys.stderr, flush=True)
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
