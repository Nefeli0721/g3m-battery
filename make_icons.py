"""生成托盘图标：电池形状，按电量档位变色。

输出标准 .ico（BMP 编码，32bpp + alpha），避免任何第三方依赖。
"""
import os
import struct

SIZE = 32


def _battery_bitmap(level: int, size: int = SIZE) -> bytearray:
    """返回 BGRA 自上而下的像素数组。level: 0..100，-1 表示未知/未连接。"""
    w = h = size
    px = bytearray(w * h * 4)
    margin = 2
    body_x0, body_x1 = 3, size - 7          # 电池主体
    body_y0, body_y1 = 8, size - 8
    nub_x0, nub_x1 = size - 6, size - 3     # 右侧电极
    nub_y0, nub_y1 = 13, size - 13

    if level < 0:
        fg = (150, 150, 150, 255)           # 灰
    elif level > 50:
        fg = (80, 210, 120, 255)            # 绿
    elif level > 20:
        fg = (60, 190, 240, 255)            # 黄
    else:
        fg = (60, 80, 240, 255)             # 红

    def put(x, y, color):
        if 0 <= x < w and 0 <= y < h:
            off = (y * w + x) * 4
            px[off:off + 4] = bytes(color)

    # 外框
    for x in range(body_x0, body_x1):
        put(x, body_y0, fg)
        put(x, body_y1 - 1, fg)
    for y in range(body_y0, body_y1):
        put(body_x0, y, fg)
        put(body_x1 - 1, y, fg)
    # 电极
    for x in range(nub_x0, nub_x1):
        put(x, nub_y0, fg)
        put(x, nub_y1 - 1, fg)
    for y in range(nub_y0, nub_y1):
        put(nub_x0, y, fg)

    # 内部填充
    if level > 0:
        inner_x0, inner_x1 = body_x0 + 2, body_x1 - 2
        inner_y0, inner_y1 = body_y0 + 2, body_y1 - 2
        span = inner_x1 - inner_x0
        fill_w = max(0, round(span * min(level, 100) / 100.0))
        for x in range(inner_x0, inner_x0 + fill_w):
            for y in range(inner_y0, inner_y1):
                put(x, y, fg)
    return px


def _ico_image(level: int, size: int = SIZE) -> bytes:
    px = _battery_bitmap(level, size)
    w = h = size
    # BITMAPINFOHEADER，高度写 2 倍（XOR + AND）
    header = struct.pack(
        "<IiiHHIIiiII",
        40, w, h * 2, 1, 32, 0, len(px), 0, 0, 0, 0,
    )
    # 图像需要自下而上
    rows = []
    for y in range(h - 1, -1, -1):
        rows.append(bytes(px[y * w * 4:(y + 1) * w * 4]))
    xor = b"".join(rows)
    # AND 掩码：全 0（用 alpha 通道）
    and_row = ((w + 31) // 32) * 4
    and_mask = b"\x00" * (and_row * h)
    return header + xor + and_mask


def write_ico(path: str, levels=(-1, 0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100)):
    images = [(level, _ico_image(level)) for level in levels]
    count = len(images)
    out = bytearray()
    out += struct.pack("<HHH", 0, 1, count)   # ICONDIR
    offset = 6 + 16 * count
    entries = bytearray()
    blobs = bytearray()
    for level, data in images:
        entries += struct.pack(
            "<BBBBHHII",
            SIZE if SIZE < 256 else 0,
            SIZE if SIZE < 256 else 0,
            0, 0, 1, 32, len(data), offset,
        )
        blobs += data
        offset += len(data)
    out += entries + blobs
    with open(path, "wb") as f:
        f.write(out)
    return path


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    icon_dir = os.path.join(here, "icons")
    os.makedirs(icon_dir, exist_ok=True)
    levels = (-1, 0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100)
    for level in levels:
        name = "unknown.ico" if level < 0 else "battery_%03d.ico" % level
        write_ico(os.path.join(icon_dir, name), levels=(level,))
        print("wrote", os.path.join(icon_dir, name))
    # 应用图标（大一点的电池）
    write_ico(os.path.join(here, "app.ico"), levels=(80,))
    print("wrote app.ico")


if __name__ == "__main__":
    main()
