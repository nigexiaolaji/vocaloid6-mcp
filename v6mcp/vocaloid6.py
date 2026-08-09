"""
VOCALOID6 编辑器操作（open_in_vocaloid6 / render_wav 预留）。

方案 A：仅用系统关联程序打开工程文件（os.startfile），零脆弱点。
方案 B：pywinauto UI 自动化（预留，后续阶段实现）。
"""

import os
import platform
import subprocess


def _detect_editor() -> bool:
    """粗检测 V6 是否安装（检查常见安装路径/注册表键）。返回 bool。"""
    if platform.system() != "Windows":
        return False
    candidates = [
        os.path.expandvars(r"%ProgramFiles%\VOCALOID6"),
        os.path.expandvars(r"%ProgramFiles(x86)%\VOCALOID6"),
        os.path.expandvars(r"%LocalAppData%\VOCALOID6"),
    ]
    for c in candidates:
        if os.path.isdir(c):
            return True
    return False


def open_in_vocaloid6(project_path: str) -> dict:
    """
    MCP 工具 open_in_vocaloid6：用系统默认程序打开工程文件。

    @return: {opened, project_path, editor_detected, hint}
    """
    if not os.path.exists(project_path):
        raise FileNotFoundError(f"工程文件不存在: {project_path}")

    editor_detected = _detect_editor()

    if platform.system() == "Windows":
        # os.startfile 使用系统文件关联（.vsqx 一般已关联到 VOCALOID6）
        os.startfile(project_path)  # noqa: S606
        opened = True
    else:
        # 非 Windows 兜底：用 xdg-open（仅提示，V6 仅 Windows）
        try:
            subprocess.Popen(["xdg-open", project_path])
            opened = True
        except FileNotFoundError:
            opened = False

    hint = ""
    if not editor_detected:
        hint = "未检测到 VOCALOID6 安装目录（可能在非默认路径）；若未打开请手动用 V6 打开该文件。"

    return {
        "opened": opened,
        "project_path": project_path,
        "editor_detected": editor_detected,
        "hint": hint,
    }


def render_wav(project_path: str, output_wav: str | None = None, timeout_sec: int = 300) -> dict:
    """
    MCP 工具 render_wav（方案 B 预留）：UI 自动化渲染 WAV。

    当前未实现，返回明确提示。后续阶段 4 用 pywinauto 实现。
    """
    return {
        "rendered": False,
        "project_path": project_path,
        "output_wav": output_wav,
        "fallback_hint": "方案 B（UI 自动化渲染）尚未实现。请手动在 VOCALOID6 中渲染导出 WAV。",
    }
