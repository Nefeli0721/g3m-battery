"""电量曲线窗口：用 Tkinter Canvas 画历史电量、充电区间与剩余时长估算。

零依赖，配色与悬浮窗一致。右键托盘 →「电量曲线…」打开。
"""
from __future__ import annotations

import time
import tkinter as tk
from tkinter import messagebox
from typing import Optional

from battery_history import (
    REASON_TEXT,
    Sample,
    estimate_remaining,
    format_duration,
)

BG = "#141821"
PANEL = "#0f1116"
GRID = "#242a36"
GRID_STRONG = "#2f3646"
TEXT = "#e8ecf4"
TEXT_DIM = "#6b7385"
LINE_DISCHARGE = "#3ddc84"
LINE_CHARGING = "#f0b429"
ACCENT_DOT = "#3ddc84"

FONT = ("Microsoft YaHei UI", 9)
FONT_SMALL = ("Microsoft YaHei UI", 8)
FONT_BIG = ("Microsoft YaHei UI", 22, "bold")
FONT_MID = ("Microsoft YaHei UI", 12)

RANGES = [(6, "6 小时"), (24, "24 小时"), (72, "3 天"), (168, "7 天")]


class CurveWindow:
    """历史电量曲线窗口（单例，关闭时隐藏而不是销毁）。"""

    def __init__(self, parent: tk.Tk, app):
        self.app = app
        self.visible = False
        self.samples: list[Sample] = []
        self._hover_x: Optional[int] = None

        self.win = tk.Toplevel(parent)
        self.win.withdraw()
        self.win.title("G3M PRO 电量曲线")
        self.win.configure(bg=PANEL)
        self.win.geometry("900x560")
        self.win.minsize(560, 360)
        self.win.protocol("WM_DELETE_WINDOW", self.hide)

        try:
            self.win.iconbitmap(self.app.app_icon_path())
        except Exception:  # noqa: BLE001
            pass

        # ---- 顶部：当前状态 + 预估
        header = tk.Frame(self.win, bg=PANEL)
        header.pack(fill="x", padx=16, pady=(12, 6))

        left = tk.Frame(header, bg=PANEL)
        left.pack(side="left")
        self.lbl_percent = tk.Label(left, text="--%", bg=PANEL, fg=TEXT, font=FONT_BIG)
        self.lbl_percent.pack(side="left")
        self.lbl_state = tk.Label(left, text="", bg=PANEL, fg=TEXT_DIM, font=FONT)
        self.lbl_state.pack(side="left", padx=(10, 0))

        right = tk.Frame(header, bg=PANEL)
        right.pack(side="right")
        self.lbl_eta = tk.Label(right, text="", bg=PANEL, fg=LINE_DISCHARGE, font=FONT_MID)
        self.lbl_eta.pack(anchor="e")
        self.lbl_eta_hint = tk.Label(right, text="", bg=PANEL, fg=TEXT_DIM, font=FONT_SMALL)
        self.lbl_eta_hint.pack(anchor="e")

        # ---- 中段：曲线
        self.canvas = tk.Canvas(self.win, bg=BG, highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True, padx=16, pady=(4, 4))
        self.canvas.bind("<Configure>", lambda _e: self._redraw())
        self.canvas.bind("<Motion>", self._on_motion)
        self.canvas.bind("<Leave>", self._on_leave)

        # ---- 底部：时间范围 + 统计
        footer = tk.Frame(self.win, bg=PANEL)
        footer.pack(fill="x", padx=16, pady=(0, 12))

        self.range_var = tk.IntVar(value=int(app.config.get("curve_range_hours", 24)))
        for hours, label in RANGES:
            btn = tk.Radiobutton(
                footer, text=label, value=hours, variable=self.range_var,
                command=self._on_range_change, bg=PANEL, fg=TEXT_DIM,
                selectcolor="#233046", activebackground=PANEL, activeforeground=TEXT,
                highlightthickness=0, bd=0, font=FONT_SMALL, indicatoron=False,
                padx=8, pady=3,
            )
            btn.pack(side="left", padx=(0, 4))

        self.lbl_stats = tk.Label(footer, text="", bg=PANEL, fg=TEXT_DIM, font=FONT_SMALL)
        self.lbl_stats.pack(side="left", padx=(12, 0))

        tk.Button(
            footer, text="清空记录", command=self._on_clear,
            bg=PANEL, fg=TEXT_DIM, activebackground=BG, activeforeground=TEXT,
            highlightthickness=0, bd=0, font=FONT_SMALL, padx=6, pady=3,
        ).pack(side="right")

    # ------------------------------------------------------------------ 外部
    def app_icon_path(self) -> str:  # 由 app 提供，便于测试替身
        return self.app.app_icon_path()

    def show(self) -> None:
        self.win.deiconify()
        self.win.lift()
        self.win.focus_set()
        self.visible = True
        self.refresh()

    def hide(self) -> None:
        self.win.withdraw()
        self.visible = False

    def refresh(self) -> None:
        """重新读取历史并重绘。"""
        span = self.range_var.get() * 3600
        now = time.time()
        self.samples = self.app.history.load(since=now - span)
        reading = getattr(self.app, "last_reading", None)
        percent = getattr(reading, "percent", None)
        state = getattr(reading, "charge_state", None)

        if reading is None:
            self.lbl_percent.configure(text="--%", fg=TEXT_DIM)
            self.lbl_state.configure(text="未连接", fg="#ef4444")
            self.lbl_eta.configure(text="")
            self.lbl_eta_hint.configure(text="")
        else:
            color = "#ef4444" if (percent or 0) <= 20 else TEXT
            self.lbl_percent.configure(text=f"{percent}%", fg=color)
            self.lbl_state.configure(text=reading.charge_label, fg=TEXT_DIM)

            est = estimate_remaining(
                self.app.history.load(since=now - 3 * 3600),
                now=now,
                window_hours=3.0,
                current_state=state,
                current_percent=percent,
            )
            if est.ok:
                self.lbl_eta.configure(
                    text=f"预计还可使用 {format_duration(est.seconds)}",
                    fg=LINE_DISCHARGE)
                self.lbl_eta_hint.configure(text="按最近 3 小时的放电速率估算")
            else:
                self.lbl_eta.configure(
                    text=REASON_TEXT.get(est.reason, "暂无法估算"), fg=TEXT_DIM)
                self.lbl_eta_hint.configure(text="")

        self.lbl_stats.configure(text=f"本区间 {len(self.samples)} 个采样点")
        self._redraw()

    # ------------------------------------------------------------------ 绘制
    def _redraw(self) -> None:
        c = self.canvas
        c.delete("all")
        w, h = c.winfo_width(), c.winfo_height()
        if w < 120 or h < 80:
            return

        left, right, top, bottom = 48, 16, 14, 28
        plot_w = w - left - right
        plot_h = h - top - bottom
        if plot_w <= 10 or plot_h <= 10:
            return

        span = self.range_var.get() * 3600
        now = time.time()
        t0 = now - span

        # 网格 + Y 轴
        for pct in (0, 25, 50, 75, 100):
            y = top + plot_h * (1 - pct / 100)
            c.create_line(left, y, left + plot_w, y,
                          fill=GRID_STRONG if pct in (0, 100) else GRID)
            c.create_text(left - 8, y, text=f"{pct}%", anchor="e",
                          fill=TEXT_DIM, font=FONT_SMALL)

        # X 轴刻度
        fmt = "%H:%M" if span <= 24 * 3600 else ("%m-%d %H:%M" if span <= 72 * 3600 else "%m-%d")
        ticks = 4 if plot_w < 520 else 6
        for i in range(ticks + 1):
            frac = i / ticks
            x = left + plot_w * frac
            t = t0 + span * frac
            anchor = "w" if i == 0 else ("e" if i == ticks else "center")
            c.create_line(x, top + plot_h, x, top + plot_h + 4, fill=GRID_STRONG)
            c.create_text(x, top + plot_h + 14, text=time.strftime(fmt, time.localtime(t)),
                          fill=TEXT_DIM, font=FONT_SMALL, anchor=anchor)

        if not self.samples:
            c.create_text(left + plot_w / 2, top + plot_h / 2,
                          text="还没有历史数据\n保持托盘运行即可自动记录",
                          fill=TEXT_DIM, font=FONT, justify="center")
            return

        def x_of(t: float) -> float:
            return left + plot_w * max(0.0, min(1.0, (t - t0) / span))

        def y_of(pct: float) -> float:
            return top + plot_h * (1 - max(0, min(100, pct)) / 100.0)

        pts = [(x_of(s.t), y_of(s.percent), s) for s in self.samples]

        # 折线：按采样点的充电状态着色
        for (x1, y1, s1), (x2, y2, s2) in zip(pts, pts[1:]):
            color = LINE_CHARGING if s2.state in (1, 2) else LINE_DISCHARGE
            c.create_line(x1, y1, x2, y2, fill=color, width=2, capstyle="round")

        # 充电区间底部标记
        for s in self.samples:
            if s.state in (1, 2):
                x = x_of(s.t)
                c.create_line(x, top + plot_h - 3, x, top + plot_h,
                              fill=LINE_CHARGING)
                break

        # 最近一个点
        last_x, last_y, last = pts[-1]
        c.create_oval(last_x - 3, last_y - 3, last_x + 3, last_y + 3,
                      fill=ACCENT_DOT, outline="")

        # 悬停提示
        if self._hover_x is not None:
            self._draw_hover(left, plot_w, top, plot_h, t0, span, pts)

    def _draw_hover(self, left, plot_w, top, plot_h, t0, span, pts) -> None:
        c = self.canvas
        target = left + max(0, min(plot_w, self._hover_x - left))
        # 找时间上最接近的采样
        target_t = t0 + span * (target - left) / plot_w
        nearest = min(pts, key=lambda p: abs(p[2].t - target_t))
        x, y, s = nearest
        c.create_line(x, top, x, top + plot_h, fill=GRID_STRONG, dash=(3, 3))
        c.create_oval(x - 3, y - 3, x + 3, y + 3, fill=TEXT, outline="")
        label = (f"{time.strftime('%m-%d %H:%M', time.localtime(s.t))}　"
                 f"{s.percent}%　"
                 f"{'充电中' if s.state == 1 else ('已充满' if s.state == 2 else '使用中')}")
        tw = 210
        tx = min(max(x + 8, left + 4), left + plot_w - tw)
        ty = max(top + 8, y - 30)
        c.create_rectangle(tx, ty, tx + tw, ty + 20, fill="#1b2130", outline=GRID_STRONG)
        c.create_text(tx + 8, ty + 10, text=label, anchor="w", fill=TEXT, font=FONT_SMALL)

    # ------------------------------------------------------------------ 事件
    def _on_motion(self, event) -> None:
        self._hover_x = event.x
        self._redraw()

    def _on_leave(self, _event) -> None:
        self._hover_x = None
        self._redraw()

    def _on_range_change(self) -> None:
        self.app.config["curve_range_hours"] = self.range_var.get()
        self.app.save_config()
        self.refresh()

    def _on_clear(self) -> None:
        if not messagebox.askyesno("清空记录", "确定清空本机保存的电量历史吗？", parent=self.win):
            return
        self.app.history.clear()
        self.refresh()
