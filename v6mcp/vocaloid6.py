"""
VOCALOID6 编辑器操作（open_in_vocaloid6 / render_wav）。

方案 A：用系统关联程序打开工程文件（os.startfile），零脆弱点。
方案 B：pywinauto UI 自动化渲染导出 WAV（尽力实现，失败时给出手动兜底）。
"""

import os
import platform
import subprocess
import time

_EDITOR_CANDIDATES = [
    os.path.expandvars(r"%ProgramFiles%\VOCALOID6\Editor\VOCALOID6.exe"),
    os.path.expandvars(r"%ProgramFiles(x86)%\VOCALOID6\Editor\VOCALOID6.exe"),
    os.path.expandvars(r"%LocalAppData%\VOCALOID6\Editor\VOCALOID6.exe"),
]


def _detect_editor() -> bool:
    """检测 V6 是否安装（检查常见安装路径）。返回 bool。"""
    if platform.system() != "Windows":
        return False
    return any(os.path.isfile(c) for c in _EDITOR_CANDIDATES)


def _editor_exe() -> str | None:
    """返回 VOCALOID6 编辑器 exe 路径（找不到返回 None）。"""
    for c in _EDITOR_CANDIDATES:
        if os.path.isfile(c):
            return c
    return None


def open_in_vocaloid6(project_path: str) -> dict:
    """
    MCP 工具 open_in_vocaloid6：用 VOCALOID6 编辑器直接打开工程文件。

    优先直接启动 VOCALOID6.exe 并传入工程路径（不依赖文件关联，最可靠）；
    exe 启动失败时用 os.startfile 系统关联兜底。

    @return: {opened, project_path, editor_detected, method, hint}
    """
    if not os.path.exists(project_path):
        raise FileNotFoundError(f"工程文件不存在: {project_path}")

    # os.startfile 需要绝对路径（相对路径会 WinError 2）
    project_path = os.path.abspath(project_path)
    editor_detected = _detect_editor()
    method = "exe"

    opened = False
    if platform.system() == "Windows":
        exe = _editor_exe()
        if exe:
            try:
                # 直接启动编辑器并传入工程路径（最可靠，不依赖文件关联）
                proc = subprocess.Popen([exe, project_path])
                time.sleep(3)
                # 编辑器进程仍在运行 = 正常加载；立即退出说明启动失败，走兜底
                if proc.poll() is None:
                    opened = True
            except Exception:
                opened = False
        if not opened:
            # 兜底：系统文件关联（.vsqx/.vpr 可能未注册关联，会失败）
            try:
                os.startfile(project_path)  # noqa: S606
                opened = True
                method = "startfile"
            except Exception:
                opened = False
    else:
        # 非 Windows 兜底：用 xdg-open（仅提示，V6 仅 Windows）
        try:
            subprocess.Popen(["xdg-open", project_path])
            opened = True
            method = "xdg-open"
        except FileNotFoundError:
            opened = False

    hint = ""
    if not editor_detected:
        hint = "未检测到 VOCALOID6 安装目录（可能在非默认路径）；若未打开请手动用 V6 打开该文件。"
    elif not opened:
        hint = "自动打开失败。请手动操作：在 VOCALOID6 中 文件→打开，选择该工程文件。"

    return {
        "opened": opened,
        "project_path": project_path,
        "editor_detected": editor_detected,
        "method": method,
        "hint": hint,
    }


# ============ 方案 B：pywinauto UI 自动化渲染 ============

def _launch_editor(project_path: str, timeout_sec: int) -> subprocess.Popen | None:
    """启动 VOCALOID6 打开工程，返回进程对象。"""
    exe = _editor_exe()
    if not exe:
        return None
    try:
        return subprocess.Popen([exe, project_path])
    except Exception:
        return None


def _find_main_window(timeout_sec: int):
    """等待并返回 VOCALOID6 主窗口（uia 后端）。超时返回 None。"""
    from pywinauto import Desktop

    deadline = time.time() + timeout_sec
    desktop = Desktop(backend="uia")
    while time.time() < deadline:
        try:
            wins = desktop.windows()
            for w in wins:
                text = w.window_text() or ""
                cls = w.class_name() or ""
                # 主窗口标题一般含工程名或 "VOCALOID"
                if "VOCALOID" in text.upper() or "VOCALOID" in cls.upper():
                    return w
        except Exception:
            pass
        time.sleep(2)
    return None


def _try_export_menu(win, output_wav: str) -> str | None:
    """尝试通过菜单导出音频（File → Export → Audio/WAV）。成功返回窗口快照，失败返回 None。

    VOCALOID6 中英文菜单名都尝试：File/文件、Export/导出、Audio/WAV。
    """
    try:
        menu = win.menu()
    except Exception:
        return None
    try:
        items = menu.items()
    except Exception:
        return None
    # 先找"文件/File"菜单
    file_menu = None
    for it in items:
        t = (it.text() or "").strip()
        if t in ("文件", "File", "ファイル", "&File"):
            file_menu = it
            break
    if file_menu is None:
        return None
    # 展开文件菜单，找"导出/Export"
    try:
        file_menu.click_input()
    except Exception:
        return None
    time.sleep(1.5)
    sub_items = []
    try:
        sub_items = menu.items()  # 重新读取
    except Exception:
        pass
    export_item = None
    for it in sub_items:
        t = (it.text() or "").strip()
        if t in ("导出", "导出音频", "Export", "Export Audio", "エクスポート"):
            export_item = it
            break
    if export_item is None:
        # 尝试直接点开文件菜单后按方向键选"导出"
        try:
            win.type_keys("{DOWN}" * 6 + "{ENTER}", set_foreground=False)
        except Exception:
            pass
        return "menu_guess"
    try:
        export_item.click_input()
    except Exception:
        return None
    time.sleep(1.5)
    return "export_clicked"


def render_wav(project_path: str, output_wav: str | None = None, timeout_sec: int = 300) -> dict:
    """
    MCP 工具 render_wav：UI 自动化渲染导出 WAV（方案 B，尽力实现）。

    流程：启动 VOCALOID6 打开工程 → 等待主窗口 → 尝试菜单导出音频 →
    在保存对话框填入输出路径 → 等待 .wav 生成。任一步失败都返回明确错误与手动兜底。

    @return: {rendered, project_path, output_wav, elapsed_sec, detail, fallback_hint}
    """
    t0 = time.time()
    result = {
        "rendered": False,
        "project_path": project_path,
        "output_wav": output_wav,
        "elapsed_sec": 0.0,
        "detail": "",
        "fallback_hint": "UI 自动化失败。请手动操作：1) 用 VOCALOID6 打开该工程；2) 菜单 文件→导出→音频(WAV)；3) 选择保存位置后导出。",
    }

    if not os.path.exists(project_path):
        result["detail"] = f"工程文件不存在: {project_path}"
        return result
    if not _detect_editor():
        result["detail"] = "未检测到 VOCALOID6 安装目录，无法自动渲染。"
        return result

    # 0) 启动编辑器打开工程
    proc = _launch_editor(project_path, timeout_sec)
    if proc is None:
        result["detail"] = "启动 VOCALOID6 失败（未找到编辑器 exe）。"
        return result
    result["detail"] += "已启动 VOCALOID6 打开工程。\n"

    # 1) 等待主窗口
    win = _find_main_window(min(timeout_sec, 60))
    if win is None:
        result["detail"] += "等待主窗口超时（编辑器可能启动较慢或有弹窗）。"
        return result
    result["detail"] += f"已找到主窗口「{win.window_text()}」。\n"

    try:
        win.set_focus()
    except Exception:
        pass

    # 2) 尝试菜单导出
    stage = _try_export_menu(win, output_wav or "")
    if stage is None:
        result["detail"] += "未能在菜单中找到导出项（界面可能非标准布局）。"
        return result
    result["detail"] += f"已触发导出操作（{stage}）。\n"

    # 3) 等待并处理保存对话框（填输出路径）
    from pywinauto import Desktop

    save_dialog = None
    deadline = time.time() + 30
    desktop = Desktop(backend="uia")
    while time.time() < deadline:
        try:
            for w in desktop.windows():
                t = (w.window_text() or "").upper()
                if "保存" in t or "EXPORT" in t or "SAVE" in t or "名前" in t:
                    save_dialog = w
                    break
            if save_dialog:
                break
        except Exception:
            pass
        time.sleep(1)

    if save_dialog is not None:
        result["detail"] += "已找到保存对话框。\n"
        try:
            # 优先找文件名编辑框，填输出路径
            edits = save_dialog.children(class_name="Edit")
            target = output_wav or ""
            if target and edits:
                edits[0].set_edit_text(target)
                time.sleep(0.5)
                save_btn = None
                for b in save_dialog.children():
                    bt = (b.window_text() or "").strip()
                    if bt in ("保存", "导出", "Save", "Export", "OK"):
                        save_btn = b
                        break
                if save_btn:
                    save_btn.click()
                else:
                    save_dialog.type_keys("{ENTER}")
        except Exception as e:
            result["detail"] += f"保存对话框操作失败：{e}\n"
    else:
        result["detail"] += "未检测到保存对话框（可能在默认目录直接导出）。\n"

    # 4) 等待 wav 文件出现
    waited = 0.0
    wav_path = None
    if output_wav:
        wav_path = output_wav
    else:
        base = os.path.splitext(project_path)[0]
        wav_path = base + ".wav"
    while waited < min(timeout_sec, 120):
        if os.path.exists(wav_path) and os.path.getsize(wav_path) > 1000:
            result["rendered"] = True
            break
        time.sleep(2)
        waited += 2

    result["elapsed_sec"] = round(time.time() - t0, 2)
    if result["rendered"]:
        result["detail"] += f"渲染完成，WAV 已生成：{wav_path}（{os.path.getsize(wav_path)} 字节）。"
        result["fallback_hint"] = ""
        result["output_wav"] = wav_path
    else:
        result["detail"] += "等待 WAV 生成超时（渲染可能未自动触发或输出路径不同）。"
    return result
