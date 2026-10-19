"""电量历史记录与剩余使用时长估算。

设计要点：
  * 历史存成 JSONL（每行一条采样），追加写、崩溃也不会坏掉整个文件
  * 采样来自托盘轮询（默认 30 秒一次），只在电量/充电状态变化时才有意义，
    但为了曲线平滑仍然全部记录
  * 超过 `max_age_days` 的数据会被裁剪；超过 2 天的老数据按 10 分钟抽稀，
    避免文件无限增长
  * 剩余时长用**最近一段连续放电区间**做线性回归，「连续」定义为相邻采样间隔
    ≤ 15 分钟（跨越休眠/关机的大缺口不参与计算）
"""
from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass
from typing import Iterable, Optional

MAX_AGE_DAYS = 14
GAP_SECONDS = 15 * 60          # 超过这个间隔视为不连续
THIN_AFTER_SECONDS = 2 * 86400  # 超过 2 天的数据开始抽稀
THIN_BUCKET_SECONDS = 10 * 60   # 抽稀粒度
MIN_SPAN_SECONDS = 10 * 60      # 至少观察 10 分钟
MIN_SAMPLES = 4                 # 至少 4 个采样点
MIN_DROP_PERCENT = 2            # 至少下降 2% 才估算
MAX_ETA_SECONDS = 7 * 86400     # 超过 7 天的估算不可信，直接判为数据不足

STATE_DISCHARGE = 0
STATE_CHARGING = 1
STATE_FULL = 2


@dataclass(frozen=True)
class Sample:
    t: float
    percent: int
    state: int


@dataclass(frozen=True)
class Estimate:
    seconds: Optional[float]
    reason: str          # ok / charging / charging_full / insufficient / stable

    @property
    def ok(self) -> bool:
        return self.reason == "ok"


REASON_TEXT = {
    "charging": "充电中，暂不估算",
    "charging_full": "已充满",
    "insufficient": "数据不足，再多采集一会儿",
    "stable": "电量没有下降，暂无法估算",
}


def format_duration(seconds: Optional[float]) -> str:
    """把秒数格式化成「X 小时 Y 分钟」这类中文描述。"""
    if seconds is None:
        return "—"
    sec = int(round(seconds))
    if sec < 60:
        return "不到 1 分钟"
    minutes = sec // 60
    if minutes < 60:
        return f"{minutes} 分钟"
    hours, minutes = divmod(minutes, 60)
    if hours < 24:
        return f"{hours} 小时 {minutes} 分钟" if minutes else f"{hours} 小时"
    days, hours = divmod(hours, 24)
    return f"{days} 天 {hours} 小时" if hours else f"{days} 天"


class History:
    """追加式电量历史。线程安全（采样线程写、UI 线程读）。"""

    def __init__(self, path: str, max_age_days: int = MAX_AGE_DAYS):
        self.path = path
        self.max_age_days = max_age_days
        self._lock = threading.Lock()
        self._last_prune = 0.0

    # -- 写 ---------------------------------------------------------
    def record(self, percent: int, state: int, ts: Optional[float] = None) -> None:
        ts = time.time() if ts is None else float(ts)
        line = json.dumps(
            {"t": round(ts, 1), "p": int(percent), "s": int(state)},
            separators=(",", ":"),
        )
        with self._lock:
            try:
                with open(self.path, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
            except OSError:
                return
            if ts - self._last_prune > 6 * 3600:
                self._last_prune = ts
                self._prune_locked(now=ts)

    def _prune_locked(self, now: Optional[float] = None) -> None:
        """裁剪过期数据，并抽稀老数据。调用方需已持有锁。"""
        now = time.time() if now is None else now
        try:
            with open(self.path, encoding="utf-8") as f:
                raw = f.read().splitlines()
        except OSError:
            return

        cutoff = now - self.max_age_days * 86400
        kept: list[str] = []
        seen_buckets: set[int] = set()
        for line in raw:
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
                t = float(item["t"])
            except (ValueError, KeyError, TypeError):
                continue
            if t < cutoff:
                continue
            if now - t > THIN_AFTER_SECONDS:
                bucket = int(t // THIN_BUCKET_SECONDS)
                if bucket in seen_buckets:
                    continue
                seen_buckets.add(bucket)
            kept.append(line)

        try:
            with open(self.path, "w", encoding="utf-8", newline="\n") as f:
                f.write("\n".join(kept) + ("\n" if kept else ""))
        except OSError:
            pass

    # -- 读 ---------------------------------------------------------
    def load(self, since: Optional[float] = None) -> list[Sample]:
        since = 0.0 if since is None else since
        out: list[Sample] = []
        try:
            with open(self.path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        item = json.loads(line)
                        sample = Sample(float(item["t"]), int(item["p"]), int(item["s"]))
                    except (ValueError, KeyError, TypeError):
                        continue
                    if sample.t >= since:
                        out.append(sample)
        except OSError:
            return []
        out.sort(key=lambda s: s.t)
        return out

    def clear(self) -> None:
        with self._lock:
            try:
                open(self.path, "w", encoding="utf-8").close()
            except OSError:
                pass


def _slope_per_second(points: Iterable[tuple[float, float]]) -> float:
    """最小二乘拟合斜率（单位：百分比/秒）。points 为 (相对时间, 百分比)。"""
    pts = list(points)
    n = len(pts)
    if n < 2:
        return 0.0
    sx = sum(p[0] for p in pts)
    sy = sum(p[1] for p in pts)
    sxx = sum(p[0] * p[0] for p in pts)
    sxy = sum(p[0] * p[1] for p in pts)
    denom = n * sxx - sx * sx
    if denom == 0:
        return 0.0
    return (n * sxy - sx * sy) / denom


def _contiguous_tail(samples: list[Sample]) -> list[Sample]:
    """从末尾往前取一段连续采样（相邻间隔 <= GAP_SECONDS）。"""
    if not samples:
        return []
    tail = [samples[-1]]
    for sample in reversed(samples[:-1]):
        if tail[-1].t - sample.t > GAP_SECONDS:
            break
        tail.append(sample)
    tail.reverse()
    return tail


def estimate_remaining(
    samples: list[Sample],
    now: Optional[float] = None,
    window_hours: float = 3.0,
    current_state: Optional[int] = None,
    current_percent: Optional[int] = None,
) -> Estimate:
    """根据最近若干小时的放电数据估算剩余可用时长。"""
    now = time.time() if now is None else now
    if current_state == STATE_FULL:
        return Estimate(None, "charging_full")
    if current_state == STATE_CHARGING:
        return Estimate(None, "charging")

    window_start = now - window_hours * 3600
    discharge = [s for s in samples if s.state == STATE_DISCHARGE and s.t >= window_start]
    # 只要最后一段连续的放电区间，跨越休眠/关机的大缺口会被切断
    discharge = _contiguous_tail(discharge)
    if len(discharge) < MIN_SAMPLES:
        return Estimate(None, "insufficient")

    span = discharge[-1].t - discharge[0].t
    if span < MIN_SPAN_SECONDS:
        return Estimate(None, "insufficient")

    drop = discharge[0].percent - discharge[-1].percent
    if drop < MIN_DROP_PERCENT:
        return Estimate(None, "insufficient")

    t0 = discharge[0].t
    slope = _slope_per_second((s.t - t0, float(s.percent)) for s in discharge)
    if slope >= 0:
        return Estimate(None, "stable")

    percent_now = float(discharge[-1].percent if current_percent is None else current_percent)
    remain = percent_now / (-slope)
    if remain <= 0 or remain > MAX_ETA_SECONDS:
        return Estimate(None, "insufficient")
    return Estimate(remain, "ok")
