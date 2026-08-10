# VOCALOID6 MCP 服务器

让 AI（通过 MCP 协议，在 atomcode 客户端中调用）自动作曲并驱动本机 VOCALOID6 编辑器，
产出可渲染歌声的工程文件（.vpr / .vsqx）。

```
用户输入歌词/想法
   ↓
[MCP 工具] list_voicebanks  → 查看本机可用歌姬（MIKU_V4X 系列等）
   ↓
[MCP 工具] compose_song    → 歌词+歌姬+情感+歌曲结构 → 旋律 MIDI → .vpr 工程
   ↓
[MCP 工具] midi_to_vocaloid → 已有 MIDI + 歌词 → .vpr 工程
   ↓
[MCP 工具] open_in_vocaloid6 → 自动打开 VOCALOID6 编辑器
   ↓
[MCP 工具] render_wav      → UI 自动化渲染导出 WAV（尽力实现，失败给手动兜底）
   ↓
得到歌声 WAV
```

## 方案定位

- **方案 A**：AI 产出 VPR/VSQX 工程文件 + 自动打开编辑器，你点一下渲染。零脆弱点。
- **方案 B**：pywinauto UI 自动化自动渲染 WAV（`render_wav`，尽力实现，失败时返回明确错误与手动步骤）。

## 安装

```bash
cd C:/Users/Admin/vocaloid6-mcp
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## 启动 MCP 服务器

```bash
python server.py
```

接入 atomcode 的 MCP 配置后（`C:/Users/Admin/.atomcode/mcp.json` 已指向本项目），AI 即可调用以下工具：

| 工具 | 功能 |
|---|---|
| `list_voicebanks` | 列出本机可用歌姬（真实声库 + V6 内置 AI 声库）|
| `compose_song` | 歌词/想法 → 旋律 MIDI → .vpr 工程（支持歌姬/情感/歌曲结构）|
| `midi_to_vocaloid` | 已有 MIDI + 歌词 → .vpr/.vsqx 工程（支持歌姬/情感）|
| `mix_songs` | 两曲混合改编（旋律/歌词/分段/infill）|
| `lyric_correct` | 日文假名 → 音节/音素；中文 → 拼音（支持自定义读音）|
| `open_in_vocaloid6` | 打开工程文件到 VOCALOID6 编辑器 |
| `render_wav` | UI 自动化渲染导出 WAV（pywinauto，尽力实现）|

## 完整写歌示例（AI 调用链）

1. `list_voicebanks` → 找到 `MIKU_V4X_Original_EVEC`
2. `lyric_correct("我爱月光照亮黑夜", lang="zh")` → 预检中文拼音
3. `compose_song(lyrics="我爱月光照亮黑夜", voice="MIKU_V4X_Original_EVEC", emotion="sad", structure="pop", key="Am", scale="minor")` → 生成 .vpr/.vsqx
4. `open_in_vocaloid6(vpr_path)` → 打开编辑器试听
5. `render_wav(vpr_path, output_wav="out.wav")` → 尝试自动渲染 WAV

## 参数速查

- **voice 歌姬**：`list_voicebanks` 返回的 name 或 comp_id；中文用户常用 `MIKU_V4X_Original_EVEC`（初音未来）
- **emotion 情感**：happy/sad/gentle/passionate/rock/calm（或中文：快乐/悲伤/温柔/激昂/摇滚/平静），控制力度/开音/颤音/音域和 Part 控制器曲线
- **structure 结构**：pop / simple / ballad（和弦进行 + 主歌/副歌/桥段/尾声）
- **key 调性**：C / Dm / Eb / F#m 或数字 0-11
- **scale 音阶**：major / minor / pentatonic / minor_penta

## 目录结构

```
vocaloid6-mcp/
├── server.py          # MCP 服务器入口（注册 7 个工具）
├── requirements.txt   # 独立依赖（含 pywinauto）
└── v6mcp/
    ├── __init__.py
    ├── lyrics.py      # 日文假名/片假名 → 音素 + 中文拼音
    ├── emotion.py     # 情感 → 表现力参数映射（DYN/BRI/CLE/GEN/OPE/颤音）
    ├── midi2vpr.py    # MIDI → VPR/VSQX 工程生成 + 声库发现/歌姬选择
    ├── compose.py     # 旋律生成（和弦进行 + 歌曲结构）+ 混合改编
    └── vocaloid6.py   # 编辑器定位/打开 + render_wav UI 自动化
```

## 状态

- [x] 方案设计文档（docs/vocaloid6-mcp-design.md）
- [x] 阶段 0：依赖与骨架
- [x] 阶段 1：midi_to_vocaloid + open_in_vocaloid6（方案 A）
- [x] 阶段 2：compose_song 作曲编排（歌姬/情感/歌曲结构）
- [x] 阶段 3：mix_songs 混合改编
- [x] 阶段 4：render_wav UI 自动化（方案 B，尽力实现）
- [x] 阶段 5：接入 atomcode MCP（mcp.json 指向本项目）
