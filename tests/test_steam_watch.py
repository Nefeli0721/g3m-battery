"""steam_watch 的单元测试（不依赖真实 Steam）。"""
from __future__ import annotations

import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from steam_watch import GameTracker, SteamWatcher, read_running_apps  # noqa: E402


class GameTrackerTests(unittest.TestCase):
    def test_start_event(self):
        t = GameTracker()
        events = t.update({"730": "CS2"})
        self.assertEqual(events, [("start", "730", "CS2")])
        self.assertTrue(t.has_running)

    def test_no_event_when_unchanged(self):
        t = GameTracker()
        t.update({"730": "CS2"})
        self.assertEqual(t.update({"730": "CS2"}), [])

    def test_end_event(self):
        t = GameTracker()
        t.update({"730": "CS2"})
        events = t.update({})
        self.assertEqual(events, [("end", "730", "CS2")])
        self.assertFalse(t.has_running)

    def test_multiple_games(self):
        t = GameTracker()
        t.update({"730": "CS2", "105600": "Terraria"})
        # 关掉一个，另一个还在
        events = t.update({"105600": "Terraria"})
        self.assertEqual(events, [("end", "730", "CS2")])
        self.assertTrue(t.has_running)
        # 全关
        events = t.update({})
        self.assertEqual(events, [("end", "105600", "Terraria")])
        self.assertFalse(t.has_running)

    def test_running_is_a_copy(self):
        t = GameTracker()
        t.update({"730": "CS2"})
        snapshot = t.running
        snapshot["999"] = "fake"
        self.assertNotIn("999", t.running)


class SteamWatcherTests(unittest.TestCase):
    def test_watcher_emits_end(self):
        snapshots = [{"730": "CS2"}, {"730": "CS2"}, {}]
        state = {"i": 0}

        def reader():
            i = min(state["i"], len(snapshots) - 1)
            state["i"] += 1
            return snapshots[i]

        watcher = SteamWatcher(interval=0.05, reader=reader)
        watcher.start()
        events = []
        deadline = time.time() + 3
        while time.time() < deadline and not events:
            try:
                events.append(watcher.out.get(timeout=0.2))
            except Exception:  # noqa: BLE001
                pass
        watcher.stop()
        watcher.join(timeout=1)
        self.assertTrue(events, "expected an event from the watcher")
        # 第一次读取是基线，不会产生 start 事件；随后应出现 end
        self.assertEqual(events[0][0], "end")


class ReadRunningAppsTests(unittest.TestCase):
    def test_returns_dict(self):
        """真实环境下应返回 dict；没有 Steam 也应优雅返回空 dict。"""
        result = read_running_apps()
        self.assertIsInstance(result, dict)
        for appid, name in result.items():
            self.assertIsInstance(appid, str)
            self.assertIsInstance(name, str)


if __name__ == "__main__":
    unittest.main()
