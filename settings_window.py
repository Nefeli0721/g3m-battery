"""设置页面：把配置项按分组渲染成一页开关，改动即时生效并落盘。

页面内容完全由 `app_settings.SECTIONS` 驱动 —— 新增配置项不需要改这个文件。
"""
from __future__ import annotations

import tkinter as tk

import app_settings

BG = "#141821"
PANEL = "#0f1116"
CARD = "#171c26"
BORDER = "#2a3140"
TEXT = "#e8ecf4"
TEXT_DIM = "#8b93a7"
ACCENT = "#3ddc84"

FONT = ("Microsoft YaHei UI", 9)
FONT_SMALL = ("Microsoft YaHei UI", 8)
FONT_SECTION = ("Microsoft YaHei UI", 10, "bold")

WIDTH = 470
HEIGHT = 700


class SettingsWindow:
    """设置窗口（单例，关闭时隐藏）。"""

    def __init__(self, parent: tk.Tk, app):
        self.app = app
        self.visible = False
        self._vars: dict[str, tk.Variable] = {}
        self._bool_labels: dict[str, tk.Label] = {}
        self._debounce: dict[str, str] = {}

        self.win = tk.Toplevel(parent)
        self.win.withdraw()
        self.win.title("G3M Battery 设置")
        self.win.configure(bg=PANEL)
        self.win.geometry(f"{WIDTH}x{HEIGHT}")
        self.win.minsize(380, 400)
        self.win.protocol("WM_DELETE_WINDOW", self.hide)
        try:
            self.win.iconbitmap(app.app_icon_path())
        except Exception:  # noqa: BLE001
            pass

        header = tk.Frame(self.win, bg=PANEL)
        header.pack(fill="x", padx=18, pady=(14, 6))
        tk.Label(header, text="设置", bg=PANEL, fg=TEXT,
                 font=("Microsoft YaHei UI", 13, "bold")).pack(side="left")
        tk.Label(header, text="改动即时生效并保存", bg=PANEL, fg=TEXT_DIM,
                 font=FONT_SMALL).pack(side="left", padx=(10, 0))

        # 可滚动区域
        container = tk.Frame(self.win, bg=PANEL)
        container.pack(fill="both", expand=True, padx=(18, 0), pady=(0, 6))
        self.canvas = tk.Canvas(container, bg=PANEL, highlightthickness=0, bd=0)
        scrollbar = tk.Scrollbar(container, orient="vertical",
                                 command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scrollbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        body = tk.Frame(self.canvas, bg=PANEL)
        self._body_id = self.canvas.create_window((0, 0), window=body, anchor="nw")
        body.bind("<Configure>", self._on_body_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.win.bind_all("<MouseWheel>", self._on_wheel, add="+")

        for title, fields in app_settings.SECTIONS:
            self._build_section(body, title, fields)

        footer = tk.Frame(self.win, bg=PANEL)
        footer.pack(fill="x", padx=18, pady=(0, 14))
        tk.Label(footer, text=f"v{getattr(self.app, 'version', '')}",
                 bg=PANEL, fg=TEXT_DIM, font=FONT_SMALL).pack(side="left")
        tk.Button(footer, text="恢复默认", command=self._on_reset,
                  bg=CARD, fg=TEXT_DIM, activebackground=BORDER,
                  activeforeground=TEXT, relief="flat", bd=0,
                  font=FONT, padx=12, pady=4).pack(side="right")
        tk.Button(footer, text="关闭", command=self.hide,
                  bg=ACCENT, fg="#0b1a12", activebackground="#2ec472",
                  activeforeground="#0b1a12", relief="flat", bd=0,
                  font=FONT, padx=18, pady=4).pack(side="right", padx=(0, 8))

        self.refresh()

    # ------------------------------------------------------------------ 滚动
    def _on_body_configure(self, _event=None) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event) -> None:
        self.canvas.itemconfigure(self._body_id, width=event.width)

    def _on_wheel(self, event) -> None:
        if not self.visible:
            return
        self.canvas.yview_scroll(int(-event.delta / 120), "units")

    # ------------------------------------------------------------------ 构建
    def _build_section(self, parent: tk.Frame, title: str, fields) -> None:
        tk.Label(parent, text=title, bg=PANEL, fg=ACCENT,
                 font=FONT_SECTION).pack(anchor="w", pady=(10, 4))
        card = tk.Frame(parent, bg=CARD, highlightthickness=1,
                        highlightbackground=BORDER)
        card.pack(fill="x", padx=(0, 12))
        for index, f in enumerate(fields):
            if index:
                tk.Frame(card, bg=BORDER, height=1).pack(fill="x", padx=12)
            self._build_row(card, f)

    def _build_row(self, parent: tk.Frame, f: app_settings.Field) -> None:
        row = tk.Frame(parent, bg=CARD)
        row.pack(fill="x", padx=12, pady=7)

        left = tk.Frame(row, bg=CARD)
        left.pack(side="left", fill="x", expand=True)
        tk.Label(left, text=f.label, bg=CARD, fg=TEXT,
                 font=FONT).pack(anchor="w")
        if f.hint:
            tk.Label(left, text=f.hint, bg=CARD, fg=TEXT_DIM, font=FONT_SMALL,
                     wraplength=250, justify="left").pack(anchor="w")

        right = tk.Frame(row, bg=CARD)
        right.pack(side="right")

        if f.kind in ("bool", "autostart"):
            if f.kind == "autostart":
                initial = app_settings.is_autostart_enabled()
            else:
                initial = bool(self.app.get_setting(f.key))
            var = tk.BooleanVar(value=initial)
            self._vars[f.key] = var

            state = tk.Label(right, text="", bg=CARD, font=FONT_SMALL)
            state.pack(side="left", padx=(0, 8))
            self._bool_labels[f.key] = state

            tk.Checkbutton(
                right, variable=var, command=lambda: self._apply(f),
                bg=CARD, activebackground=CARD, selectcolor=BORDER,
                fg=ACCENT, activeforeground=ACCENT,
                highlightthickness=0, bd=0,
            ).pack(side="left")
        elif f.kind == "int":
            var = tk.IntVar(value=int(self.app.get_setting(f.key)))
            self._vars[f.key] = var
            holder = tk.Frame(right, bg=CARD)
            holder.pack()
            spin = tk.Spinbox(holder, from_=f.minimum, to=f.maximum, width=5,
                              textvariable=var, bg=PANEL, fg=TEXT,
                              buttonbackground=CARD, relief="flat", bd=0,
                              highlightthickness=1, highlightbackground=BORDER,
                              insertbackground=TEXT, font=FONT,
                              command=lambda: self._apply(f))
            spin.pack(side="left")
            spin.bind("<KeyRelease>", lambda _e, fl=f: self._apply_debounced(fl))
            spin.bind("<FocusOut>", lambda _e, fl=f: self._apply(fl))
            if f.unit:
                tk.Label(holder, text=f.unit, bg=CARD, fg=TEXT_DIM,
                         font=FONT_SMALL).pack(side="left", padx=(4, 0))
        elif f.kind == "choice":
            var = tk.IntVar(value=int(self.app.get_setting(f.key)))
            self._vars[f.key] = var
            holder = tk.Frame(right, bg=CARD)
            holder.pack()
            for value, label in f.choices:
                tk.Radiobutton(holder, text=label, value=value, variable=var,
                               command=lambda: self._apply(f),
                               bg=CARD, fg=TEXT_DIM, selectcolor=BORDER,
                               activebackground=CARD, activeforeground=TEXT,
                               highlightthickness=0, bd=0,
                               font=FONT_SMALL, indicatoron=False,
                               padx=6, pady=2).pack(side="left", padx=(0, 3))

    # ------------------------------------------------------------------ 逻辑
    def _apply(self, f: app_settings.Field) -> None:
        try:
            value = self._vars[f.key].get()
        except tk.TclError:
            return
        if f.kind == "autostart":
            self.app.set_autostart(bool(value))
        else:
            self.app.set_setting(f.key, value)
        self._sync_bool_labels()

    def _apply_debounced(self, f: app_settings.Field) -> None:
        pending = self._debounce.pop(f.key, None)
        if pending:
            try:
                self.win.after_cancel(pending)
            except Exception:  # noqa: BLE001
                pass
        self._debounce[f.key] = self.win.after(500, lambda: self._apply(f))

    def _sync_bool_labels(self) -> None:
        for key, label in self._bool_labels.items():
            var = self._vars.get(key)
            if var is None:
                continue
            try:
                on = bool(var.get())
            except tk.TclError:
                continue
            label.configure(text="已开启" if on else "已关闭",
                            fg=ACCENT if on else TEXT_DIM)

    def _on_reset(self) -> None:
        for f in app_settings.all_fields():
            if f.kind == "autostart":
                continue
            self.app.set_setting(f.key, f.default)
        self.refresh()

    def refresh(self) -> None:
        """把当前配置同步回控件（恢复默认、外部改动后调用）。"""
        for f in app_settings.all_fields():
            var = self._vars.get(f.key)
            if var is None:
                continue
            try:
                if f.kind == "autostart":
                    var.set(app_settings.is_autostart_enabled())
                else:
                    var.set(self.app.get_setting(f.key))
            except Exception:  # noqa: BLE001
                pass
        self._sync_bool_labels()

    # ------------------------------------------------------------------ 显隐
    def show(self) -> None:
        self.refresh()
        self.win.deiconify()
        self.win.lift()
        self.win.focus_set()
        self.visible = True

    def hide(self) -> None:
        self.win.withdraw()
        self.visible = False
