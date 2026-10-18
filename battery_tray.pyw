"""HECATE G3M PRO 电量托盘 + 桌面悬浮窗。

纯标准库实现（tkinter + ctypes 调 Win32），无需安装任何依赖，也不需要管理员权限。

用法：
    pythonw battery_tray.pyw          正常启动（托盘 + 悬浮窗）
    pythonw battery_tray.pyw --tray   仅托盘（不显示悬浮窗）
    python battery_tray.py --demo     演示模式，不访问真实设备
"""
from __future__ import annotations

import ctypes
import json
import os
import queue
import sys
import threading
import time
import tkinter as tk
from ctypes import wintypes

HERE = os.path.dirname(os.path.abspath(__file__))
ICON_DIR = os.path.join(HERE, "icons")
CONFIG_PATH = os.path.join(HERE, "settings.json")

# 让 g3m_battery 可导入
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import g3m_battery  # noqa: E402
import battery_history  # noqa: E402
import battery_curve  # noqa: E402

HISTORY_PATH = os.path.join(HERE, "history.jsonl")


def ensure_icons() -> None:
    """托盘图标是运行时生成的：首次运行或图标缺失时自动补上。"""
    if os.path.isdir(ICON_DIR) and os.path.exists(
            os.path.join(ICON_DIR, "battery_050.ico")):
        return
    try:
        import make_icons
        make_icons.main()
    except Exception:  # noqa: BLE001
        pass

# ------------------------------------------------------------------ Win32
user32 = ctypes.WinDLL("user32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(
    LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
)

WM_DESTROY = 0x0002
WM_COMMAND = 0x0111
WM_LBUTTONUP = 0x0202
WM_LBUTTONDBLCLK = 0x0203
WM_RBUTTONUP = 0x0205
WM_CONTEXTMENU = 0x007B
WM_APP = 0x8000
WM_TRAYICON = WM_APP + 1

NIM_ADD = 0x00000000
NIM_MODIFY = 0x00000001
NIM_DELETE = 0x00000002
NIF_MESSAGE = 0x00000001
NIF_ICON = 0x00000002
NIF_TIP = 0x00000004

IMAGE_ICON = 1
LR_LOADFROMFILE = 0x00000010
SM_CXSMICON = 49
SM_CYSMICON = 50

WS_POPUP = 0x80000000
PM_REMOVE = 0x0001


class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.UINT),
        ("style", wintypes.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
        ("hIconSm", wintypes.HICON),
    ]


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("hWnd", wintypes.HWND),
        ("uID", wintypes.UINT),
        ("uFlags", wintypes.UINT),
        ("uCallbackMessage", wintypes.UINT),
        ("hIcon", wintypes.HICON),
        ("szTip", wintypes.WCHAR * 128),
        ("dwState", wintypes.DWORD),
        ("dwStateMask", wintypes.DWORD),
        ("szInfo", wintypes.WCHAR * 256),
        ("uVersion", wintypes.UINT),
        ("szInfoTitle", wintypes.WCHAR * 64),
        ("dwInfoFlags", wintypes.DWORD),
        ("guidItem", ctypes.c_byte * 16),
        ("hBalloonIcon", wintypes.HICON),
    ]


class MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("message", wintypes.UINT),
        ("wParam", wintypes.WPARAM),
        ("lParam", wintypes.LPARAM),
        ("time", wintypes.DWORD),
        ("pt", wintypes.POINT),
    ]


user32.DefWindowProcW.restype = LRESULT
user32.DefWindowProcW.argtypes = [
    wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
]
user32.RegisterClassExW.argtypes = [ctypes.POINTER(WNDCLASSEXW)]
user32.CreateWindowExW.restype = wintypes.HWND
user32.CreateWindowExW.argtypes = [
    wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, ctypes.c_void_p,
]
user32.DestroyWindow.argtypes = [wintypes.HWND]
user32.LoadImageW.restype = wintypes.HANDLE
user32.LoadImageW.argtypes = [
    wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT,
    ctypes.c_int, ctypes.c_int, wintypes.UINT,
]
user32.DestroyIcon.argtypes = [wintypes.HICON]
user32.GetSystemMetrics.argtypes = [ctypes.c_int]
user32.PeekMessageW.argtypes = [
    ctypes.POINTER(MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT, wintypes.UINT
]
user32.TranslateMessage.argtypes = [ctypes.POINTER(MSG)]
user32.DispatchMessageW.argtypes = [ctypes.POINTER(MSG)]
user32.RegisterWindowMessageW.restype = wintypes.UINT
user32.RegisterWindowMessageW.argtypes = [wintypes.LPCWSTR]
user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]

shell32.Shell_NotifyIconW.argtypes = [
    wintypes.DWORD, ctypes.POINTER(NOTIFYICONDATAW)
]
kernel32.CreateMutexW.restype = wintypes.HANDLE
kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
kernel32.GetLastError.restype = wintypes.DWORD
# 必须显式声明 restype：默认 c_int 会把 64 位 HMODULE 截断成 32 位，
# 拿它当 hInstance 传给窗口类注册会偶发访问冲突（曾经导致托盘进程随机崩溃）。
kernel32.GetModuleHandleW.restype = wintypes.HMODULE
kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]


def icon_for(percent: int | None) -> str:
    if percent is None:
        return os.path.join(ICON_DIR, "unknown.ico")
    level = max(0, min(100, int(round(percent / 10.0)) * 10))
    return os.path.join(ICON_DIR, "battery_%03d.ico" % level)


class TrayIcon:
    """Win32 托盘图标（Shell_NotifyIcon），tooltip 随电量更新。"""

    def __init__(self, on_left, on_right, on_double):
        self._on_left = on_left
        self._on_right = on_right
        self._on_double = on_double
        self._hwnd = None
        self._icon = None
        self._ticon = None
        self._proc_ref = WNDPROC(self._wndproc)
        self._taskbar_created = user32.RegisterWindowMessageW("TaskbarCreated")
        self._class_name = "G3MBatteryTrayWnd"
        self._create_window()
        self._add()

    # -- 内部 -------------------------------------------------------
    def _create_window(self):
        hinst = kernel32.GetModuleHandleW(None)
        wc = WNDCLASSEXW()
        wc.cbSize = ctypes.sizeof(WNDCLASSEXW)
        wc.style = 0
        wc.lpfnWndProc = self._proc_ref
        wc.hInstance = hinst
        wc.lpszClassName = self._class_name
        if not user32.RegisterClassExW(ctypes.byref(wc)):
            err = ctypes.get_last_error()
            if err != 1410:  # 类已注册
                raise ctypes.WinError(err)
        self._hwnd = user32.CreateWindowExW(
            0, self._class_name, "G3M Battery", WS_POPUP,
            0, 0, 0, 0, None, None, hinst, None,
        )
        if not self._hwnd:
            raise ctypes.WinError(ctypes.get_last_error())

    def _wndproc(self, hwnd, msg, wparam, lparam):
        if msg == WM_TRAYICON:
            ev = lparam & 0xFFFF
            if ev == WM_LBUTTONUP:
                self._on_left()
                return 0
            if ev == WM_LBUTTONDBLCLK:
                self._on_double()
                return 0
            if ev in (WM_RBUTTONUP, WM_CONTEXTMENU):
                self._on_right()
                return 0
            return 0
        if msg == self._taskbar_created and self._taskbar_created:
            self._add()
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _make_ticon(self) -> NOTIFYICONDATAW:
        nid = NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        nid.hWnd = self._hwnd
        nid.uID = 1
        nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
        nid.uCallbackMessage = WM_TRAYICON
        nid.hIcon = self._icon or 0
        nid.szTip = "G3M PRO"
        return nid

    def _load_icon(self, path: str):
        cx = user32.GetSystemMetrics(SM_CXSMICON)
        cy = user32.GetSystemMetrics(SM_CYSMICON)
        return user32.LoadImageW(
            None, path, IMAGE_ICON, cx, cy, LR_LOADFROMFILE
        )

    def _add(self):
        if self._icon:
            user32.DestroyIcon(self._icon)
        self._icon = self._load_icon(icon_for(None))
        self._ticon = self._make_ticon()
        shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(self._ticon))

    def update(self, percent: int | None, tooltip: str):
        if not self._ticon:
            return
        new_icon = self._load_icon(icon_for(percent))
        old = self._icon
        self._icon = new_icon
        self._ticon.hIcon = new_icon
        self._ticon.uFlags = NIF_ICON | NIF_TIP | NIF_MESSAGE
        self._ticon.szTip = tooltip[:127]
        shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(self._ticon))
        if old:
            user32.DestroyIcon(old)

    def pump(self):
        """在 Tk 的 after 循环里派发 Win32 消息。"""
        msg = MSG()
        while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_REMOVE):
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

    def cursor_pos(self) -> tuple[int, int]:
        pt = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        return pt.x, pt.y

    def destroy(self):
        if self._ticon:
            shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(self._ticon))
            self._ticon = None
        if self._icon:
            user32.DestroyIcon(self._icon)
            self._icon = None
        if self._hwnd:
            user32.DestroyWindow(self._hwnd)
            self._hwnd = None


# ------------------------------------------------------------------ 采样线程
class Sampler(threading.Thread):
    def __init__(self, interval: float, demo: bool = False,
                 demo_percent: int | None = None):
        super().__init__(daemon=True)
        self.interval = interval
        self.demo = demo
        self.demo_percent = demo_percent
        self.out: queue.Queue = queue.Queue()
        self._stop = threading.Event()
        self._force = threading.Event()
        self._demo_level = 90

    def force(self):
        self._force.set()

    def stop(self):
        self._stop.set()

    def run(self):
        while not self._stop.is_set():
            if self.demo:
                if self.demo_percent is not None:
                    level = self.demo_percent
                else:
                    # 缓慢波动，方便验证界面
                    level = 90 - int((time.time() / 7) % 5)
                fake = g3m_battery.BatteryReading(
                    percent=level, charge_state=0, payload=bytes(6),
                    raw=bytes(64))
                self.out.put(("ok", level, fake))
            else:
                try:
                    r = g3m_battery.query_battery()
                    self.out.put(("ok", r.percent, r))
                except g3m_battery.DeviceNotFound:
                    self.out.put(("offline", None, "未检测到 G3M PRO 接收器"))
                except g3m_battery.NoResponse:
                    self.out.put(("offline", None, "设备未响应（可能已休眠）"))
                except Exception as exc:  # noqa: BLE001
                    self.out.put(("error", None, str(exc)))
            waited = 0.0
            while waited < self.interval and not self._stop.is_set():
                if self._force.wait(0.2):
                    self._force.clear()
                    break
                waited += 0.2


# ------------------------------------------------------------------ 悬浮窗
class FloatWindow:
    def __init__(self, root: tk.Tk, app: "BatteryApp"):
        self.app = app
        self.root = root
        self.visible = False
        self.win = tk.Toplevel(root)
        self.win.withdraw()
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.configure(bg="#0f1116")

        self.frame = tk.Frame(self.win, bg="#141821", bd=0, highlightthickness=1,
                              highlightbackground="#2a3140")
        self.frame.pack(fill="both", expand=True)

        # 顶部：设备名 + 状态点
        top = tk.Frame(self.frame, bg="#141821")
        top.pack(fill="x", padx=10, pady=(8, 0))
        tk.Label(top, text="G3M PRO", bg="#141821", fg="#8b93a7",
                 font=("Microsoft YaHei UI", 9)).pack(side="left")
        self.dot = tk.Canvas(top, width=10, height=10, bg="#141821",
                             highlightthickness=0)
        self.dot.pack(side="right")
        self._dot_id = self.dot.create_oval(2, 2, 8, 8, fill="#3ddc84", outline="")

        # 大数字
        self.pct = tk.Label(self.frame, text="--%", bg="#141821", fg="#e8ecf4",
                            font=("Microsoft YaHei UI", 26, "bold"))
        self.pct.pack(pady=(0, 2))

        # 进度条
        self.bar = tk.Canvas(self.frame, height=6, width=170, bg="#141821",
                             highlightthickness=0)
        self.bar.pack(padx=10, pady=(0, 6))
        self._bar_bg = self.bar.create_rectangle(0, 0, 170, 6, fill="#242a36", outline="")
        self._bar_fg = self.bar.create_rectangle(0, 0, 0, 6, fill="#3ddc84", outline="")

        self.status = tk.Label(self.frame, text="正在读取…", bg="#141821",
                               fg="#6b7385", font=("Microsoft YaHei UI", 8))
        self.status.pack(pady=(0, 8))
        self.charge = tk.Label(self.frame, text="", bg="#141821", fg="#3ddc84",
                               font=("Microsoft YaHei UI", 8, "bold"))
        self.charge.pack(pady=(0, 6))

        # 拖动
        for w in (self.frame, top, self.pct, self.status, self.bar):
            w.bind("<Button-1>", self._drag_start)
            w.bind("<B1-Motion>", self._drag_move)
            w.bind("<Button-3>", self._popup_menu)

        self._drag = (0, 0)
        self.win.update_idletasks()
        self._place_initial()

    # -- 位置 -------------------------------------------------------
    def _place_initial(self):
        pos = self.app.config.get("window_pos")
        w = 200
        h = self.win.winfo_reqheight()
        if pos:
            x, y = pos
        else:
            sw = self.win.winfo_screenwidth()
            x, y = sw - w - 40, 80
        self.win.geometry(f"{w}x{h}+{int(x)}+{int(y)}")

    def _drag_start(self, event):
        self._drag = (event.x_root - self.win.winfo_x(),
                      event.y_root - self.win.winfo_y())

    def _drag_move(self, event):
        x = event.x_root - self._drag[0]
        y = event.y_root - self._drag[1]
        self.win.geometry(f"+{x}+{y}")

    def _popup_menu(self, event=None):
        self.app.show_menu()

    # -- 状态 -------------------------------------------------------
    def show(self):
        self.win.deiconify()
        self.win.attributes("-topmost", True)
        self.visible = True

    def hide(self):
        self.win.withdraw()
        self.visible = False
        self.app.save_window_pos(self.win.winfo_x(), self.win.winfo_y())

    def toggle(self):
        self.hide() if self.visible else self.show()

    def render(self, state: str, percent: int | None, detail):
        if state == "ok" and percent is not None:
            fill = int(170 * max(0, min(100, percent)) / 100)
            if percent > 50:
                color, text_fg = "#3ddc84", "#e8ecf4"
            elif percent > 20:
                color, text_fg = "#f0b429", "#f0b429"
            else:
                color, text_fg = "#ef4444", "#ef4444"
            self.pct.configure(text=f"{percent}%", fg=text_fg)
            self.bar.coords(self._bar_fg, 0, 0, fill, 6)
            self.bar.itemconfigure(self._bar_fg, fill=color)
            self.dot.itemconfigure(self._dot_id, fill="#3ddc84")
            self.status.configure(text=time.strftime("更新于 %H:%M:%S"), fg="#6b7385")
            # 充电状态：优先用核心层算好的 label（它会把“100% + 充电中”归为已充满）
            label = getattr(detail, "charge_label", "")
            charge_state = getattr(detail, "charge_state", None)
            if label == "已充满":
                self.charge.configure(text="✓ 已充满", fg="#3ddc84")
            elif label == "充电中":
                self.charge.configure(text="⚡ 充电中", fg="#3ddc84")
            elif label == "使用中":
                self.charge.configure(text="使用中", fg="#6b7385")
            elif charge_state is not None:
                self.charge.configure(text="", fg="#6b7385")
            else:
                self.charge.configure(text="")
        else:
            self.pct.configure(text="--%", fg="#6b7385")
            self.bar.coords(self._bar_fg, 0, 0, 0, 6)
            self.dot.itemconfigure(self._dot_id, fill="#ef4444")
            self.status.configure(text=detail or "未连接", fg="#ef4444")
            self.charge.configure(text="")


# ------------------------------------------------------------------ 主程序
class BatteryApp:
    def __init__(self, demo: bool = False, show_window: bool = True,
                 demo_percent: int | None = None):
        self.demo = demo
        self.config = self._load_config()
        self.history = battery_history.History(HISTORY_PATH)
        self.last_reading = None
        self.curve = None

        self.root = tk.Tk()
        self.root.withdraw()
        self.root.title("G3M Battery")

        self.window = FloatWindow(self.root, self)
        self.tray = TrayIcon(
            on_left=self.window.toggle,
            on_right=self.show_menu,
            on_double=self._force_refresh,
        )

        interval = float(self.config.get("interval", 30))
        self.sampler = Sampler(interval=interval, demo=demo,
                               demo_percent=demo_percent)
        self.sampler.start()

        self.menu = tk.Menu(self.root, tearoff=0)
        self.menu.add_command(label="立即刷新", command=self._force_refresh)
        self.menu.add_command(label="电量曲线…", command=self.show_curve)
        self.menu.add_command(label="显示/隐藏悬浮窗", command=self.window.toggle)
        self.menu.add_separator()
        self.menu.add_command(label=f"v{g3m_battery.__version__}", state="disabled")
        self.menu.add_separator()
        self.menu.add_command(label="退出", command=self.quit)

        if show_window:
            self.window.show()

        self.root.after(100, self._tick)
        self.root.protocol("WM_DELETE_WINDOW", self.quit)
        self.last_percent = None

    # -- 配置 -------------------------------------------------------
    def _load_config(self) -> dict:
        try:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {"interval": 30}

    def save_config(self) -> None:
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(self.config, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def save_window_pos(self, x: int, y: int):
        self.config["window_pos"] = [x, y]
        self.save_config()

    def app_icon_path(self) -> str:
        return os.path.join(HERE, "app.ico")

    # -- 菜单 / 动作 ------------------------------------------------
    def show_curve(self):
        if self.curve is None:
            self.curve = battery_curve.CurveWindow(self.root, self)
        self.curve.show()

    def show_menu(self):
        try:
            x, y = self.tray.cursor_pos()
            self.menu.tk_popup(x, y)
        finally:
            self.menu.grab_release()

    def _force_refresh(self):
        self.sampler.force()

    # -- 定时 -------------------------------------------------------
    def _tick(self):
        try:
            self.tray.pump()
        except Exception:
            pass
        updated = False
        state = percent = detail = None
        while True:
            try:
                state, percent, detail = self.sampler.out.get_nowait()
            except queue.Empty:
                break
            updated = True
            self.window.render(state, percent, detail)
            if state == "ok" and percent is not None:
                if hasattr(detail, "charge_state"):
                    self.last_reading = detail
                    if not self.demo:
                        try:
                            self.history.record(percent, int(detail.charge_state))
                        except Exception:
                            pass
                label = getattr(detail, "charge_label", "")
                tip = f"G3M PRO — 电量 {percent}%"
                if label and getattr(detail, "charge_state", 0):
                    tip += f"（{label}）"
            else:
                self.last_reading = None
                tip = f"G3M PRO — {detail or '未连接'}"
            self.tray.update(percent if state == "ok" else None, tip)
            self.last_percent = percent if state == "ok" else None
        if updated and self.curve is not None and self.curve.visible:
            try:
                self.curve.refresh()
            except Exception:
                pass
        self.root.after(150, self._tick)

    def quit(self):
        try:
            self.save_window_pos(self.window.win.winfo_x(), self.window.win.winfo_y())
        except Exception:
            pass
        try:
            self.sampler.stop()
            # 等采样线程真正退出再结束解释器，否则 daemon 线程会在 finalize 时
            # 触发 "PyEval_RestoreThread ... GIL" 致命错误（Python 3.13+）
            self.sampler.join(timeout=2.0)
        except Exception:
            pass
        try:
            self.tray.destroy()
        except Exception:
            pass
        self.root.quit()
        self.root.destroy()

    def run(self):
        self.root.mainloop()


def main(argv: list[str]) -> int:
    demo = "--demo" in argv
    show_window = "--tray" not in argv
    demo_percent = None
    if "--demo-percent" in argv:
        try:
            demo_percent = int(argv[argv.index("--demo-percent") + 1])
            demo = True
        except (IndexError, ValueError):
            pass

    # 单实例
    mutex = kernel32.CreateMutexW(None, False, "G3MBatteryTray_SingleInstance")
    if kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        return 0

    ensure_icons()
    app = BatteryApp(demo=demo, show_window=show_window, demo_percent=demo_percent)
    if "--curve" in argv:
        app.show_curve()
    app.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
