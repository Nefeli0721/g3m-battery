"""检测 Steam 游戏的启动 / 退出。

数据来源是 Steam 客户端自己维护的注册表：::

    HKEY_CURRENT_USER\\Software\\Valve\\Steam\\Apps\\<appid>
        Name    (REG_SZ)    游戏名
        Running (REG_DWORD) 1 = 正在运行

比枚举进程可靠得多 —— 不用猜哪些子进程是 Steam 自己的 helper，
也不用维护一大堆排除名单。Steam 没装/没运行时就返回空，功能自动失效。

本模块只做「读取快照 → 状态机产出事件」，Win32 相关部分集中在
`read_running_apps()`，便于在没有 Steam 的环境里单测状态机。
"""
from __future__ import annotations

import queue
import threading
from typing import Callable

try:
    import winreg
except ImportError:  # 非 Windows
    winreg = None  # type: ignore[assignment]

STEAM_APPS_KEY = r"Software\Valve\Steam\Apps"

# 事件元组：(kind, appid, name)，kind 取 "start" / "end"
GameEvent = tuple[str, str, str]


def read_running_apps() -> dict[str, str]:
    """返回 {appid: 游戏名}，只包含 Running == 1 的条目。"""
    if winreg is None:
        return {}
    running: dict[str, str] = {}
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, STEAM_APPS_KEY) as apps:
            index = 0
            while True:
                try:
                    appid = winreg.EnumKey(apps, index)
                except OSError:
                    break
                index += 1
                try:
                    with winreg.OpenKey(apps, appid) as key:
                        try:
                            value, _ = winreg.QueryValueEx(key, "Running")
                        except OSError:
                            continue
                        if not isinstance(value, int) or value != 1:
                            continue
                        try:
                            name, _ = winreg.QueryValueEx(key, "Name")
                        except OSError:
                            name = ""
                except OSError:
                    continue
                running[appid] = str(name) if name else f"App {appid}"
    except OSError:
        return {}
    return running


class GameTracker:
    """纯状态机：喂入快照，产出 start / end 事件。"""

    def __init__(self) -> None:
        self._running: dict[str, str] = {}

    @property
    def running(self) -> dict[str, str]:
        return dict(self._running)

    @property
    def has_running(self) -> bool:
        return bool(self._running)

    def update(self, snapshot: dict[str, str]) -> list[GameEvent]:
        events: list[GameEvent] = []
        for appid, name in snapshot.items():
            if appid not in self._running:
                events.append(("start", appid, name))
        for appid, name in self._running.items():
            if appid not in snapshot:
                events.append(("end", appid, name))
        self._running = dict(snapshot)
        return events


class SteamWatcher(threading.Thread):
    """后台线程：每 `interval` 秒读一次注册表，把事件放进 `out` 队列。"""

    def __init__(self, interval: float = 5.0,
                 reader: Callable[[], dict[str, str]] = read_running_apps):
        # 非 daemon：退出时必须显式 stop()+join()，避免解释器 finalize 时
        # 线程还卡在 wait 里导致 GIL 致命错误。
        super().__init__(daemon=False)
        self.interval = interval
        self.reader = reader
        self.tracker = GameTracker()
        self.out: queue.Queue[GameEvent] = queue.Queue()
        self._stop_event = threading.Event()

    def stop(self) -> None:
        self._stop_event.set()

    def run(self) -> None:
        # 先读一次，建立基线，避免把启动前就在跑的游戏当成「刚开始」
        try:
            self.tracker.update(self.reader())
        except Exception:  # noqa: BLE001
            pass
        while not self._stop_event.wait(self.interval):
            try:
                snapshot = self.reader()
            except Exception:  # noqa: BLE001
                continue
            for event in self.tracker.update(snapshot):
                self.out.put(event)
