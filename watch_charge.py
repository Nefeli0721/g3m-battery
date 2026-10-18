"""观察充电状态位随时间的变化，用来确认是否存在「已充满」(state=2)。

用法: python watch_charge.py [秒数] [采样间隔]
状态一旦变成 2 会立即打印并提前退出。
"""
import sys
import time

import g3m_battery


def main() -> int:
    duration = float(sys.argv[1]) if len(sys.argv) > 1 else 300
    interval = float(sys.argv[2]) if len(sys.argv) > 2 else 3

    start = time.time()
    last = None
    samples = 0
    while time.time() - start < duration:
        stamp = time.strftime("%H:%M:%S")
        try:
            r = g3m_battery.query_battery()
            key = (r.percent, r.charge_state)
            samples += 1
            if key != last:
                print(f"{stamp}  {r.percent:3d}%  state={r.charge_state}  "
                      f"payload={r.payload.hex(' ')}  <- 变化")
                last = key
            else:
                print(f"{stamp}  {r.percent:3d}%  state={r.charge_state}")
            if r.charge_state == 2:
                print("\n*** 观测到 state=2（已充满）！***")
                return 0
        except Exception as exc:  # noqa: BLE001
            print(f"{stamp}  [错误] {exc}")
        time.sleep(interval)

    print(f"\n{duration:.0f} 秒内共 {samples} 次采样，未观测到 state=2。")
    return 5


if __name__ == "__main__":
    raise SystemExit(main())
