"""battery_history 的单元测试（stdlib unittest，无第三方依赖）。

运行：
    python -m unittest discover -s tests -v
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from battery_history import (  # noqa: E402
    History,
    Sample,
    estimate_remaining,
    format_duration,
)

HOUR = 3600.0


def make_series(start_t, hours, from_pct, to_pct, step_min=5, state=0):
    """生成一段线性放电序列。"""
    points = []
    step = step_min * 60
    n = int(hours * HOUR / step)
    for i in range(n + 1):
        frac = i / n
        points.append(Sample(
            t=start_t + i * step,
            percent=round(from_pct + (to_pct - from_pct) * frac),
            state=state,
        ))
    return points


class EstimateTests(unittest.TestCase):
    def test_linear_discharge(self):
        now = time.time()
        # 6 小时从 100% 掉到 40%，即 10%/小时；当前 40% -> 约 4 小时
        series = make_series(now - 6 * HOUR, 6, 100, 40)
        est = estimate_remaining(series, now=now, current_percent=40)
        self.assertTrue(est.ok, est.reason)
        self.assertAlmostEqual(est.seconds / HOUR, 4.0, delta=0.3)

    def test_charging_is_not_estimated(self):
        now = time.time()
        series = make_series(now - 6 * HOUR, 6, 100, 40)
        est = estimate_remaining(series, now=now, current_state=1)
        self.assertFalse(est.ok)
        self.assertEqual(est.reason, "charging")

    def test_full_is_not_estimated(self):
        now = time.time()
        series = make_series(now - 6 * HOUR, 6, 100, 40)
        est = estimate_remaining(series, now=now, current_state=2)
        self.assertEqual(est.reason, "charging_full")

    def test_insufficient_when_too_few(self):
        now = time.time()
        series = [Sample(now - 120, 90, 0), Sample(now - 60, 90, 0), Sample(now, 90, 0)]
        self.assertEqual(estimate_remaining(series, now=now).reason, "insufficient")

    def test_insufficient_when_drop_too_small(self):
        now = time.time()
        # 6 小时只掉 1%，低于 MIN_DROP_PERCENT
        series = make_series(now - 6 * HOUR, 6, 91, 90)
        self.assertEqual(estimate_remaining(series, now=now).reason, "insufficient")

    def test_big_gap_is_ignored(self):
        now = time.time()
        # 旧的一段 100->60（模拟前天），之后休眠 12 小时，最近 1 小时 60->58
        old = make_series(now - 30 * HOUR, 2, 100, 60)
        recent = make_series(now - 1 * HOUR, 1, 60, 58, step_min=5)
        series = old + recent
        est = estimate_remaining(series, now=now, window_hours=3, current_percent=58)
        self.assertTrue(est.ok, est.reason)
        # 最近这段速率约 2%/小时 -> 58% 大约 29 小时，但受 MAX_ETA 限制仍未超限
        self.assertGreater(est.seconds / HOUR, 20)

    def test_flat_is_not_estimated(self):
        now = time.time()
        series = [Sample(now - i * 300, 80, 0) for i in range(20, -1, -1)]
        self.assertEqual(estimate_remaining(series, now=now).reason, "insufficient")


class FormatTests(unittest.TestCase):
    def test_format_duration(self):
        self.assertEqual(format_duration(None), "—")
        self.assertEqual(format_duration(30), "不到 1 分钟")
        self.assertEqual(format_duration(90), "1 分钟")
        self.assertEqual(format_duration(3600), "1 小时")
        self.assertEqual(format_duration(3660), "1 小时 1 分钟")
        self.assertEqual(format_duration(90000), "1 天 1 小时")


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "history.jsonl")
        self.history = History(self.path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_record_and_load(self):
        now = time.time()
        self.history.record(90, 0, ts=now - 10)
        self.history.record(89, 1, ts=now - 5)
        samples = self.history.load()
        self.assertEqual(len(samples), 2)
        self.assertEqual(samples[0].percent, 90)
        self.assertEqual(samples[1].state, 1)
        self.assertLessEqual(samples[0].t, samples[1].t)

    def test_load_since_filters(self):
        now = time.time()
        self.history.record(90, 0, ts=now - 7200)
        self.history.record(80, 0, ts=now - 60)
        samples = self.history.load(since=now - 3600)
        self.assertEqual(len(samples), 1)
        self.assertEqual(samples[0].percent, 80)

    def test_prune_drops_old_data(self):
        now = time.time()
        self.history.record(50, 0, ts=now - 40 * 86400)   # 超过 14 天
        self.history.record(90, 0, ts=now - 60)
        self.history._prune_locked(now=now)
        samples = self.history.load()
        self.assertEqual(len(samples), 1)
        self.assertEqual(samples[0].percent, 90)

    def test_bad_lines_are_skipped(self):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write('{"t": 1, "p": 90, "s": 0}\n')
            f.write("not json\n")
            f.write('{"t": "x"}\n')
            f.write('{"t": 2, "p": 89, "s": 0}\n')
        self.assertEqual(len(self.history.load()), 2)

    def test_clear(self):
        self.history.record(90, 0)
        self.history.clear()
        self.assertEqual(self.history.load(), [])


if __name__ == "__main__":
    unittest.main()
