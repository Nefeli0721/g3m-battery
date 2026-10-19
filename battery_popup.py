"""低电量提醒弹窗。

不是系统通知，是一个真正置顶的小窗口 —— 免得游戏关掉后通知被错过。
风格与悬浮窗/曲线窗口保持一致。
"""
from __future__ import annotations

import tkinter as tk

BG = "#141821"
BORDER = "#2f3646"
TEXT = "#e8ecf4"
TEXT_DIM = "#8b93a7"
WARN = "#f0b429"
DANGER = "#ef4444"
OK = "#3ddc84"

FONT = ("Microsoft YaHei UI", 9)
FONT_SMALL = ("Microsoft YaHei UI", 8)
FONT_BIG = ("Microsoft YaHei UI", 30, "bold")
FONT_TITLE = ("Microsoft YaHei UI", 10, "bold")

AUTO_CLOSE_SECONDS = 60


class LowBatteryPopup:
    """置顶提醒窗口：显示电量、阈值、刚结束的游戏名。"""

    def __init__(self, parent: tk.Tk, *, percent: int, threshold: int,
                 game_name: str = "", device: str = "G3M PRO",
                 sound: bool = True, on_dismiss=None, on_snooze=None):
        self.parent = parent
        self.on_dismiss = on_dismiss
        self.on_snooze = on_snooze
        self._closed = False
        self._remaining = AUTO_CLOSE_SECONDS

        self.win = tk.Toplevel(parent)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.configure(bg=BG)
        try:
            self.win.attributes("-alpha", 0.98)
        except Exception:  # noqa: BLE001
            pass

        outer = tk.Frame(self.win, bg=BG, highlightthickness=1,
                         highlightbackground=BORDER)
        outer.pack(fill="both", expand=True)

        # 标题行
        title = tk.Frame(outer, bg=BG)
        title.pack(fill="x", padx=18, pady=(14, 0))
        tk.Label(title, text="⚠  鼠标电量不足", bg=BG, fg=WARN,
                 font=FONT_TITLE).pack(side="left")
        tk.Label(title, text=device, bg=BG, fg=TEXT_DIM,
                 font=FONT_SMALL).pack(side="right")

        # 大号百分比
        tk.Label(outer, text=f"{percent}%", bg=BG, fg=DANGER, font=FONT_BIG
                 ).pack(pady=(6, 0))

        # 说明文字
        if game_name:
            reason = f"「{game_name}」已退出，电量低于设定阈值 {threshold}%，建议现在充电。"
        else:
            reason = f"电量低于设定阈值 {threshold}%，建议现在充电。"
        tk.Label(outer, text=reason, bg=BG, fg=TEXT, font=FONT,
                 wraplength=330, justify="center").pack(padx=18, pady=(2, 10))

        # 按钮
        buttons = tk.Frame(outer, bg=BG)
        buttons.pack(pady=(0, 6))
        tk.Button(buttons, text="稍后提醒", command=self._snooze,
                  bg="#1b2130", fg=TEXT_DIM, activebackground="#242a36",
                  activeforeground=TEXT, relief="flat", bd=0,
                  font=FONT, padx=14, pady=5).pack(side="left", padx=(0, 8))
        tk.Button(buttons, text="知道了", command=self._dismiss,
                  bg=OK, fg="#0b1a12", activebackground="#2ec472",
                  activeforeground="#0b1a12", relief="flat", bd=0,
                  font=FONT, padx=18, pady=5).pack(side="left")

        # 自动关闭倒计时
        self.countdown = tk.Label(outer, text="", bg=BG, fg=TEXT_DIM, font=FONT_SMALL)
        self.countdown.pack(pady=(0, 10))

        self.win.update_idletasks()
        self._center()
        self._tick_countdown()

        try:
            if sound:
                import winsound
                winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
        except Exception:  # noqa: BLE001
            pass

    # -- 布局 -------------------------------------------------------
    def _center(self) -> None:
        self.win.update_idletasks()
        w = max(self.win.winfo_reqwidth(), 360)
        h = self.win.winfo_reqheight()
        sw = self.win.winfo_screenwidth()
        sh = self.win.winfo_screenheight()
        x = (sw - w) // 2
        y = int(sh * 0.28)
        self.win.geometry(f"{w}x{h}+{x}+{y}")

    def _tick_countdown(self) -> None:
        if self._closed:
            return
        if self._remaining <= 0:
            self._dismiss()
            return
        self.countdown.configure(text=f"{self._remaining} 秒后自动关闭")
        self._remaining -= 1
        self.win.after(1000, self._tick_countdown)

    # -- 动作 -------------------------------------------------------
    def _close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self.win.destroy()
        except Exception:  # noqa: BLE001
            pass

    def _dismiss(self) -> None:
        self._close()
        if self.on_dismiss:
            self.on_dismiss()

    def _snooze(self) -> None:
        self._close()
        if self.on_snooze:
            self.on_snooze()
