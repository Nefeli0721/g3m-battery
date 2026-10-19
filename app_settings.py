"""配置项定义（单一数据源）与开机自启的读写。

`SECTIONS` 既是默认值来源，也是设置页面的渲染依据 —— 加一项配置只需要
在这里加一行，设置页会自动出现对应的控件。
"""
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from typing import Any, Sequence

CONFIG_NAME = "settings.json"

# 开机自启：往「启动」文件夹放一个 .vbs（免 COM，最省事也最稳）
STARTUP_FILE = "G3M Battery.vbs"
LEGACY_LNK = "G3M PRO Battery.lnk"      # 旧版安装脚本创建的快捷方式


@dataclass(frozen=True)
class Field:
    key: str
    label: str
    kind: str                      # bool / int / choice / autostart
    default: Any = False
    hint: str = ""
    minimum: int = 0
    maximum: int = 100
    unit: str = ""
    choices: Sequence[tuple[Any, str]] = field(default_factory=tuple)


SECTIONS: Sequence[tuple[str, Sequence[Field]]] = (
    ("常规", (
        Field("interval", "电量刷新间隔", "int", 30,
              "越短越及时，但会增加 USB 查询次数", 5, 600, "秒"),
        Field("show_widget_on_start", "启动时显示悬浮窗", "bool", True),
        Field("autostart", "开机自动启动", "autostart", False,
              "在「启动」文件夹放置快捷方式"),
    )),
    ("悬浮窗", (
        Field("widget_topmost", "始终置顶", "bool", True,
              "关掉后会被其它窗口盖住"),
        Field("widget_opacity", "不透明度", "int", 98,
              "调低会半透明，方便不挡视线", 40, 100, "%"),
    )),
    ("低电量弹窗", (
        Field("low_battery_popup_enabled", "启用低电量弹窗", "bool", True,
              "Steam 游戏结束后，电量低于阈值就弹窗"),
        Field("low_battery_threshold", "电量阈值", "int", 20,
              "低于这个电量才提醒", 5, 50, "%"),
        Field("popup_on_low_anytime", "不限游戏：电量低于阈值也弹", "bool", False,
              "默认只在游戏结束后提醒"),
        Field("popup_sound", "弹窗时发出提示音", "bool", True),
        Field("steam_watch_enabled", "监视 Steam 游戏", "bool", True,
              "读取 Steam 自己的注册表判断游戏是否在运行"),
    )),
    ("电量曲线", (
        Field("record_history", "记录电量历史", "bool", True,
              "关闭后曲线停止增长（已有数据保留）"),
        Field("curve_range_hours", "曲线默认范围", "choice", 24,
              choices=((6, "6 小时"), (24, "24 小时"),
                       (72, "3 天"), (168, "7 天"))),
    )),
)

# 兼容旧配置键：老版本用的是 steam_popup_enabled
RENAMES = {"steam_popup_enabled": "low_battery_popup_enabled"}


def all_fields() -> list[Field]:
    return [f for _title, fields in SECTIONS for f in fields]


def defaults() -> dict[str, Any]:
    return {f.key: f.default for f in all_fields() if f.kind != "autostart"}


def merge(loaded: Any) -> dict[str, Any]:
    """把磁盘上的配置并到默认值上，并做旧键迁移与类型校正。"""
    cfg = defaults()
    if not isinstance(loaded, dict):
        return cfg
    data = dict(loaded)
    for old, new in RENAMES.items():
        if old in data and new not in data:
            data[new] = data.pop(old)
    for f in all_fields():
        if f.key not in data:
            continue
        value = data[f.key]
        try:
            if f.kind == "bool":
                cfg[f.key] = bool(value)
            elif f.kind == "int":
                cfg[f.key] = max(f.minimum, min(f.maximum, int(value)))
            elif f.kind == "choice":
                allowed = [c[0] for c in f.choices]
                cfg[f.key] = value if value in allowed else f.default
        except (TypeError, ValueError):
            cfg[f.key] = f.default
    if "window_pos" in data:
        cfg["window_pos"] = data["window_pos"]
    return cfg


# ------------------------------------------------------------------ 开机自启
def startup_dir() -> str:
    return os.path.join(os.environ.get("APPDATA", ""),
                        r"Microsoft\Windows\Start Menu\Programs\Startup")


def startup_target() -> str:
    return os.path.join(startup_dir(), STARTUP_FILE)


def is_autostart_enabled() -> bool:
    return (os.path.exists(startup_target())
            or os.path.exists(os.path.join(startup_dir(), LEGACY_LNK)))


def set_autostart(enabled: bool, source_vbs: str) -> bool:
    """写入/删除启动项，返回操作后是否处于启用状态。"""
    target = startup_target()
    legacy = os.path.join(startup_dir(), LEGACY_LNK)
    try:
        if enabled:
            if not os.path.exists(source_vbs):
                return False
            os.makedirs(startup_dir(), exist_ok=True)
            shutil.copyfile(source_vbs, target)
        else:
            for path in (target, legacy):
                if os.path.exists(path):
                    os.remove(path)
    except OSError:
        pass
    return is_autostart_enabled()
