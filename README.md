# VOCALOID6 MCP 服务器

让 AI（通过 MCP 协议，在 atomcode 客户端中调用）自动作曲并驱动本机 VOCALOID6 编辑器，
产出可渲染歌声的工程文件（.vpr / .vsqx）。

```
用户输入歌词/想法
   ↓
[MCP 工具] compose_song      → 生成旋律 MIDI（MIDI-GPT 或降级模板）
   ↓
[MCP 工具] midi_to_vocaloid  → MIDI + 歌词 → .vpr 工程文件
   ↓
[MCP 工具] open_in_vocaloid6 → 自动打开 VOCALOID6 编辑器
   ↓
你在编辑器里点渲染 → 得到歌声 WAV
```

## 方案定位

- **方案 A（当前实现）**：AI 产出 VPR/VSQX 工程文件 + 自动打开编辑器，你点一下渲染。零脆弱点。
- **方案 B（预留）**：UI 自动化自动渲染 WAV（`render_wav`，pywinauto，后续阶段实现）。
- 详细设计见 `../all-in-one-ai-midi-pipeline/docs/vocaloid6-mcp-design.md`。

## 安装

```bash
cd /d/MIDI/vocaloid6-mcp
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## 启动 MCP 服务器

```bash
python server.py
```

接入 atomcode 的 MCP 配置后，AI 即可调用以下工具：

| 工具 | 功能 |
|---|---|
| `compose_song` | 歌词/想法 → 旋律 MIDI（MIDI-GPT 或降级模板）|
| `midi_to_vocaloid` | MIDI + 歌词 → .vpr/.vsqx 工程文件 |
| `mix_songs` | 两曲混合改编（旋律/歌词/分段/infill）|
| `lyric_correct` | 日文歌词 → 音节/音素预检 |
| `open_in_vocaloid6` | 打开工程文件到 VOCALOID6 编辑器 |

## 目录结构

```
vocaloid6-mcp/
├── server.py          # MCP 服务器入口（注册工具）
├── requirements.txt   # 独立依赖（不污染流水线环境）
└── v6mcp/
    ├── __init__.py
    ├── lyrics.py      # 日文分词 + 音素映射
    ├── midi2vpr.py    # MIDI → VPR/VSQX 工程生成
    ├── compose.py     # 旋律生成（降级模板）+ 混合改编
    └── vocaloid6.py   # 编辑器定位/打开（方案 A）
```

## 状态

- [x] 方案设计文档（docs/vocaloid6-mcp-design.md）
- [ ] 阶段 0：依赖与骨架
- [ ] 阶段 1：midi_to_vocaloid + open_in_vocaloid6（方案 A）
- [ ] 阶段 2：compose_song 作曲编排
- [ ] 阶段 3：mix_songs 混合改编
- [ ] 阶段 4：render_wav UI 自动化（方案 B）
- [ ] 阶段 5：接入 atomcode MCP
