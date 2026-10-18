"""只读探测：看看除百分比外，固件是否还暴露原始电压/ADC。

- CMD 0x1A: 状态块（已知：电量 + 充电状态）
- CMD 0x03: 设备信息（读 ~34 字节）
- CMD 0x07: 通用读存储块（len + offset）

全部为只读命令，不修改任何设置。
"""
import sys

import g3m_battery as g


def ascii_of(data: bytes) -> str:
    return "".join(chr(b) if 32 <= b < 127 else "." for b in data)


def probe(name: str, frame: bytes, expect_cmd: int, wait: float = 1.2):
    iface = g.find_vendor_interface()
    if iface is None:
        print("设备未连接")
        return
    with g.HidDevice(iface.path) as dev:
        dev.read_reports(0.05)
        dev.write_report(frame)
        import time
        deadline = time.time() + wait
        while time.time() < deadline:
            for rep in dev.read_reports(0.15):
                if len(rep) < 9:
                    continue
                if rep[0] != 0x04 or rep[3] != expect_cmd:
                    continue
                print(f"\n=== {name} (cmd=0x{expect_cmd:02X}) ===")
                print("请求:", frame[:8].hex(" "), "...")
                print("响应:", rep[:48].hex(" "))
                print("状态[7]:", hex(rep[7]))
                payload = rep[8:]
                print("payload[8..]:", payload[:40].hex(" "))
                print("ASCII      :", ascii_of(payload[:40]))
                # 猜 16 位小端整数，找像 mV(3000..4400) 的值
                vals = []
                for i in range(0, min(len(payload) - 1, 32), 1):
                    v = payload[i] | (payload[i + 1] << 8)
                    if 2800 <= v <= 4500:
                        vals.append((i, v))
                print("疑似电压(mV)候选:", vals if vals else "无")
                return
        print(f"\n=== {name}: 无响应 ===")


if __name__ == "__main__":
    probe("CMD 0x1A 状态块", g.build_frame(0x1A, 6, 0), 0x1A)
    probe("CMD 0x03 设备信息", g.build_frame(0x03, 34, 0), 0x03)
    probe("CMD 0x07 读存储块 offset=0 len=16",
          g.build_frame(0x07, 16, 0), 0x07)
    probe("CMD 0x07 读存储块 offset=0x40 len=16",
          g.build_frame(0x07, 16, 0x40), 0x07)
