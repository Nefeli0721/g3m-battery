"""HECATE G3M Pro 电量读取核心模块（纯标准库，无需管理员权限，无需安装依赖）。

设备：HECATE G3M Pro 2.4G 接收器
  VID 0x320F / PID 0x706E，厂商字符串 "Telink"，USB 描述 "G3M PRO"
通道：MI_01 下的 COL04（UsagePage 0xFF1C / Usage 0x92），
      输出报告 64 字节 → 输入报告 64 字节，FILE_FLAG_OVERLAPPED。

协议（静态反编译 + 动态抓包双向验证）：
  请求帧 64 字节：
    [0]    0x04                 报告 ID
    [1]    sum & 0xFF           校验和低（sum = Σ frame[3..63]）
    [2]    (sum >> 8) & 0xFF    校验和高
    [3]    0x1A                 命令码 CMD_STATUS（读状态块）
    [4]    0x06                 请求返回字节数
    [5]    0x00                 offset 低
    [6]    0x00                 offset 高
    [7]    0x00
    [8..63] 0x00
  响应帧 64 字节：
    [3] 必须回显 0x1A            （不匹配视为无效帧，继续读）
    [7] 0x00 = 成功
        0xFF = 错误 -102
        0xFE = 错误 -103
    [8] 电量百分比 0..100（整数，无缩放）
    [9] 充电状态：0=放电  1=充电中  2=已充满
    [10..13] 其余状态块字节（App 未使用，含义未知）

  可选握手帧：命令 0xAA、(len=0)，响应 [8]==0xFF 表示设备就绪。
  App 本身在部分路径会先握手再读电量；直接读 0x1A 通常也能成功。
"""
from __future__ import annotations

import ctypes
import sys
import time
from ctypes import wintypes
from dataclasses import dataclass
from typing import Optional

# ---------------------------------------------------------------- Win32 常量
GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
FILE_SHARE_READ = 0x1
FILE_SHARE_WRITE = 0x2
OPEN_EXISTING = 3
FILE_FLAG_OVERLAPPED = 0x40000000
ERROR_IO_PENDING = 997
INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value

DIGCF_PRESENT = 0x02
DIGCF_DEVICEINTERFACE = 0x10

TARGET_VID = 0x320F
TARGET_PID = 0x706E
VENDOR_USAGE_PAGE = 0xFF1C

REPORT_ID = 0x04
REPORT_LEN = 64
CMD_STATUS = 0x1A
CMD_HELLO = 0xAA
STATUS_LEN = 6

CHARGE_LABELS = {0: "使用中", 1: "充电中", 2: "已充满"}


class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_uint32),
        ("Data2", ctypes.c_uint16),
        ("Data3", ctypes.c_uint16),
        ("Data4", ctypes.c_ubyte * 8),
    ]


class SP_DEVICE_INTERFACE_DATA(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("InterfaceClassGuid", GUID),
        ("Flags", wintypes.DWORD),
        ("Reserved", ctypes.c_void_p),
    ]


class HIDD_ATTRIBUTES(ctypes.Structure):
    _fields_ = [
        ("Size", ctypes.c_ulong),
        ("VendorID", ctypes.c_ushort),
        ("ProductID", ctypes.c_ushort),
        ("VersionNumber", ctypes.c_ushort),
    ]


class HIDP_CAPS(ctypes.Structure):
    _fields_ = [
        ("Usage", ctypes.c_ushort),
        ("UsagePage", ctypes.c_ushort),
        ("InputReportByteLength", ctypes.c_ushort),
        ("OutputReportByteLength", ctypes.c_ushort),
        ("FeatureReportByteLength", ctypes.c_ushort),
        ("Reserved", ctypes.c_ushort * 17),
        ("NumberLinkCollectionNodes", ctypes.c_ushort),
        ("NumberInputButtonCaps", ctypes.c_ushort),
        ("NumberInputValueCaps", ctypes.c_ushort),
        ("NumberInputDataIndices", ctypes.c_ushort),
        ("NumberOutputButtonCaps", ctypes.c_ushort),
        ("NumberOutputValueCaps", ctypes.c_ushort),
        ("NumberOutputDataIndices", ctypes.c_ushort),
        ("NumberFeatureButtonCaps", ctypes.c_ushort),
        ("NumberFeatureValueCaps", ctypes.c_ushort),
        ("NumberFeatureDataIndices", ctypes.c_ushort),
    ]


class OVERLAPPED(ctypes.Structure):
    _fields_ = [
        ("Internal", ctypes.c_void_p),
        ("InternalHigh", ctypes.c_void_p),
        ("Offset", wintypes.DWORD),
        ("OffsetHigh", wintypes.DWORD),
        ("hEvent", wintypes.HANDLE),
    ]


setupapi = ctypes.WinDLL("setupapi", use_last_error=True)
hid = ctypes.WinDLL("hid", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
ole32 = ctypes.windll.ole32

setupapi.SetupDiGetClassDevsW.restype = wintypes.HANDLE
setupapi.SetupDiGetClassDevsW.argtypes = [
    ctypes.POINTER(GUID), ctypes.c_wchar_p, ctypes.c_void_p, wintypes.DWORD]
setupapi.SetupDiEnumDeviceInterfaces.argtypes = [
    wintypes.HANDLE, ctypes.c_void_p, ctypes.POINTER(GUID), wintypes.DWORD,
    ctypes.POINTER(SP_DEVICE_INTERFACE_DATA)]
setupapi.SetupDiGetDeviceInterfaceDetailW.argtypes = [
    wintypes.HANDLE, ctypes.POINTER(SP_DEVICE_INTERFACE_DATA), ctypes.c_void_p,
    wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
setupapi.SetupDiDestroyDeviceInfoList.argtypes = [wintypes.HANDLE]
hid.HidD_GetAttributes.argtypes = [wintypes.HANDLE, ctypes.POINTER(HIDD_ATTRIBUTES)]
hid.HidD_GetProductString.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.ULONG]
hid.HidD_GetPreparsedData.argtypes = [wintypes.HANDLE, ctypes.POINTER(ctypes.c_void_p)]
hid.HidD_FreePreparsedData.argtypes = [ctypes.c_void_p]
hid.HidP_GetCaps.argtypes = [ctypes.c_void_p, ctypes.POINTER(HIDP_CAPS)]
kernel32.CreateFileW.restype = wintypes.HANDLE
kernel32.CreateFileW.argtypes = [
    ctypes.c_wchar_p, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
    wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
kernel32.CreateEventW.restype = wintypes.HANDLE
kernel32.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, ctypes.c_wchar_p]
kernel32.WriteFile.argtypes = [
    wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
kernel32.ReadFile.argtypes = [
    wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
kernel32.GetOverlappedResult.argtypes = [
    wintypes.HANDLE, ctypes.POINTER(OVERLAPPED), ctypes.POINTER(wintypes.DWORD),
    wintypes.BOOL]
kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
kernel32.CancelIoEx.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

HID_GUID = "{4d1e55b2-f16f-11cf-88cb-001111000030}"


class DeviceNotFound(RuntimeError):
    pass


class NoResponse(RuntimeError):
    pass


class ProtocolError(RuntimeError):
    pass


# ---------------------------------------------------------------- 帧构造
def build_frame(cmd: int, length: int = 0, offset: int = 0) -> bytes:
    """按 App 的方式构造 64 字节请求帧（含 16 位字节和校验）。"""
    frame = bytearray(REPORT_LEN)
    frame[0] = REPORT_ID
    frame[3] = cmd & 0xFF
    frame[4] = length & 0xFF
    frame[5] = offset & 0xFF
    frame[6] = (offset >> 8) & 0xFF
    total = sum(frame[3:REPORT_LEN])
    frame[1] = total & 0xFF
    frame[2] = (total >> 8) & 0xFF
    return bytes(frame)


def battery_request() -> bytes:
    return build_frame(CMD_STATUS, STATUS_LEN, 0)


def hello_request() -> bytes:
    return build_frame(CMD_HELLO, 0, 0)


# ---------------------------------------------------------------- 设备枚举
@dataclass
class HidInterface:
    path: str
    vid: int
    pid: int
    product: str
    usage_page: int
    usage: int
    in_len: int
    out_len: int


def enumerate_hid_interfaces() -> list[HidInterface]:
    guid = GUID()
    ole32.CLSIDFromString(HID_GUID, ctypes.byref(guid))
    devs = setupapi.SetupDiGetClassDevsW(
        ctypes.byref(guid), None, None, DIGCF_PRESENT | DIGCF_DEVICEINTERFACE)
    if devs == INVALID_HANDLE_VALUE:
        return []
    result: list[HidInterface] = []
    idx = 0
    try:
        while True:
            did = SP_DEVICE_INTERFACE_DATA()
            did.cbSize = ctypes.sizeof(did)
            if not setupapi.SetupDiEnumDeviceInterfaces(
                    devs, None, ctypes.byref(guid), idx, ctypes.byref(did)):
                break
            idx += 1
            need = wintypes.DWORD(0)
            setupapi.SetupDiGetDeviceInterfaceDetailW(
                devs, ctypes.byref(did), None, 0, ctypes.byref(need), None)
            if not need.value:
                continue
            buf = ctypes.create_string_buffer(need.value)
            ctypes.cast(buf, ctypes.POINTER(wintypes.DWORD))[0] = 8
            if not setupapi.SetupDiGetDeviceInterfaceDetailW(
                    devs, ctypes.byref(did), buf, need.value, ctypes.byref(need), None):
                continue
            path = ctypes.wstring_at(ctypes.addressof(buf) + 4)

            # 用 0 权限打开只为读属性；键盘/鼠标专有集合可能拒绝，跳过即可
            h = kernel32.CreateFileW(
                path, 0, FILE_SHARE_READ | FILE_SHARE_WRITE, None, OPEN_EXISTING, 0, None)
            if h == INVALID_HANDLE_VALUE:
                continue
            try:
                attr = HIDD_ATTRIBUTES()
                attr.Size = ctypes.sizeof(attr)
                if not hid.HidD_GetAttributes(h, ctypes.byref(attr)):
                    continue
                product = ""
                pbuf = ctypes.create_unicode_buffer(256)
                if hid.HidD_GetProductString(h, pbuf, ctypes.sizeof(pbuf)):
                    product = pbuf.value
                usage_page = usage = in_len = out_len = 0
                prep = ctypes.c_void_p()
                if hid.HidD_GetPreparsedData(h, ctypes.byref(prep)):
                    caps = HIDP_CAPS()
                    if hid.HidP_GetCaps(prep, ctypes.byref(caps)) == 0x00110000:
                        usage_page = caps.UsagePage
                        usage = caps.Usage
                        in_len = caps.InputReportByteLength
                        out_len = caps.OutputReportByteLength
                    hid.HidD_FreePreparsedData(prep)
                result.append(HidInterface(
                    path=path, vid=attr.VendorID, pid=attr.ProductID,
                    product=product, usage_page=usage_page, usage=usage,
                    in_len=in_len, out_len=out_len))
            finally:
                kernel32.CloseHandle(h)
    finally:
        setupapi.SetupDiDestroyDeviceInfoList(devs)
    return result


def find_vendor_interface() -> Optional[HidInterface]:
    """找到 G3M Pro 的厂商配置接口（COL04 / FF1C）。"""
    candidates = [i for i in enumerate_hid_interfaces()
                  if i.vid == TARGET_VID and i.pid == TARGET_PID]
    if not candidates:
        return None
    for i in candidates:
        if i.usage_page == VENDOR_USAGE_PAGE and i.out_len == REPORT_LEN:
            return i
    for i in candidates:
        if "col04" in i.path.lower() and i.out_len == REPORT_LEN:
            return i
    for i in candidates:
        if i.out_len == REPORT_LEN:
            return i
    return None


def is_connected() -> bool:
    return find_vendor_interface() is not None


# ---------------------------------------------------------------- 设备 I/O
class HidDevice:
    def __init__(self, path: str):
        self._h = kernel32.CreateFileW(
            path, GENERIC_READ | GENERIC_WRITE,
            FILE_SHARE_READ | FILE_SHARE_WRITE, None,
            OPEN_EXISTING, FILE_FLAG_OVERLAPPED, None)
        if self._h == INVALID_HANDLE_VALUE:
            raise ctypes.WinError(ctypes.get_last_error())

    def close(self) -> None:
        if getattr(self, "_h", None) and self._h != INVALID_HANDLE_VALUE:
            kernel32.CloseHandle(self._h)
            self._h = INVALID_HANDLE_VALUE

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def write_report(self, payload: bytes, timeout_ms: int = 2000) -> int:
        buf = ctypes.create_string_buffer(bytes(payload), len(payload))
        ov = OVERLAPPED()
        ev = kernel32.CreateEventW(None, True, False, None)
        ov.hEvent = ev
        written = wintypes.DWORD(0)
        try:
            ok = kernel32.WriteFile(
                self._h, buf, len(payload), ctypes.byref(written), ctypes.byref(ov))
            if not ok:
                err = ctypes.get_last_error()
                if err != ERROR_IO_PENDING:
                    raise ctypes.WinError(err)
                if kernel32.WaitForSingleObject(ev, timeout_ms) != 0:
                    kernel32.CancelIoEx(self._h, ctypes.byref(ov))
                    raise NoResponse("写报告超时")
                if not kernel32.GetOverlappedResult(
                        self._h, ctypes.byref(ov), ctypes.byref(written), False):
                    raise ctypes.WinError(ctypes.get_last_error())
        finally:
            kernel32.CloseHandle(ev)
        return written.value

    def read_reports(self, seconds: float) -> list[bytes]:
        out: list[bytes] = []
        deadline = time.time() + seconds
        ev = kernel32.CreateEventW(None, True, False, None)
        try:
            while time.time() < deadline:
                buf = ctypes.create_string_buffer(256)
                ov = OVERLAPPED()
                ov.hEvent = ev
                got = wintypes.DWORD(0)
                ok = kernel32.ReadFile(
                    self._h, buf, 256, ctypes.byref(got), ctypes.byref(ov))
                if not ok:
                    err = ctypes.get_last_error()
                    if err != ERROR_IO_PENDING:
                        break
                    remain = int((deadline - time.time()) * 1000)
                    if remain <= 0:
                        kernel32.CancelIoEx(self._h, ctypes.byref(ov))
                        break
                    if kernel32.WaitForSingleObject(ev, min(80, remain)) != 0:
                        kernel32.CancelIoEx(self._h, ctypes.byref(ov))
                        kernel32.GetOverlappedResult(
                            self._h, ctypes.byref(ov), ctypes.byref(got), True)
                        continue
                    if not kernel32.GetOverlappedResult(
                            self._h, ctypes.byref(ov), ctypes.byref(got), False):
                        break
                out.append(buf.raw[: got.value])
        finally:
            kernel32.CloseHandle(ev)
        return out


# ---------------------------------------------------------------- 结果对象
@dataclass
class BatteryReading:
    percent: int
    charge_state: int          # 0=放电 1=充电中 2=已充满
    payload: bytes             # 6 字节状态块
    raw: bytes                 # 完整 64 字节响应帧
    device: str = "G3M PRO"

    @property
    def charging(self) -> bool:
        return self.charge_state in (1, 2)

    @property
    def charge_label(self) -> str:
        # 实测：G3M PRO 充到 100% 后设备仍报 state=1（官方软件此时也显示“闪电”图标），
        # 从不报 state=2。所以 100% 且插线时按“已充满”展示更符合直觉。
        if self.charge_state == 1 and self.percent >= 100:
            return "已充满"
        if self.charge_state == 2:
            return "已充满"
        return CHARGE_LABELS.get(self.charge_state, f"状态{self.charge_state}")

    def __str__(self) -> str:
        return f"{self.device} 电量 {self.percent}% ({self.charge_label})"


# ---------------------------------------------------------------- 高层 API
def _match_status_response(report: bytes) -> Optional[BatteryReading]:
    """从一条 input report 里解析电量；不是 0x1A 的应答就返回 None。"""
    if len(report) < 9 + STATUS_LEN:
        return None
    if report[0] != REPORT_ID or report[3] != CMD_STATUS:
        return None
    status = report[7]
    if status == 0xFF:
        raise ProtocolError("设备返回错误 -102")
    if status == 0xFE:
        raise ProtocolError("设备返回错误 -103")
    percent = report[8]
    if percent > 100:
        percent = 100
    payload = bytes(report[8: 8 + STATUS_LEN])
    return BatteryReading(
        percent=percent,
        charge_state=report[9],
        payload=payload,
        raw=bytes(report),
    )


def hello(dev: HidDevice, retries: int = 3, delay: float = 0.05) -> bool:
    """设备就绪握手（CMD 0xAA），成功条件 resp[7]==0 && resp[8]==0xFF。"""
    for _ in range(retries):
        dev.write_report(hello_request())
        for rep in dev.read_reports(0.25):
            if len(rep) > 8 and rep[3] == CMD_HELLO and rep[7] == 0x00:
                return rep[8] == 0xFF
        time.sleep(delay)
    return False


def query_battery(timeout: float = 1.5, handshake: bool = False) -> BatteryReading:
    """查询一次电量 + 充电状态。失败抛 DeviceNotFound / NoResponse / ProtocolError。"""
    iface = find_vendor_interface()
    if iface is None:
        raise DeviceNotFound("未找到 HECATE G3M PRO 接收器（VID_320F / PID_706E）")

    with HidDevice(iface.path) as dev:
        if handshake:
            hello(dev)
        dev.read_reports(0.03)            # 丢弃残留帧
        dev.write_report(battery_request())
        deadline = time.time() + timeout
        while time.time() < deadline:
            for rep in dev.read_reports(0.15):
                try:
                    reading = _match_status_response(rep)
                except ProtocolError:
                    raise
                if reading is not None:
                    return reading
    raise NoResponse("设备没有返回电量帧（鼠标可能已休眠或关机）")


# ---------------------------------------------------------------- CLI
def main(argv: list[str]) -> int:
    import argparse
    import json as _json

    ap = argparse.ArgumentParser(
        description="读取 HECATE G3M PRO 鼠标电量与充电状态")
    ap.add_argument("-n", "--repeat", type=int, default=1, help="连续读取次数")
    ap.add_argument("-i", "--interval", type=float, default=5.0, help="间隔秒数")
    ap.add_argument("--json", action="store_true", help="以 JSON 输出")
    ap.add_argument("--raw", action="store_true", help="打印原始帧")
    ap.add_argument("--hello", action="store_true", help="读取前先发 0xAA 握手")
    ap.add_argument("--list", action="store_true", help="列出匹配的 HID 接口")
    ap.add_argument("--frame", action="store_true", help="只打印将要发送的请求帧")
    args = ap.parse_args(argv)

    if args.frame:
        f = battery_request()
        print("请求帧:", f.hex(" "))
        print("校验和: 0x%02X%02X (sum=%d)" % (f[2], f[1], f[2] * 256 + f[1]))
        return 0

    if args.list:
        found = False
        for i in enumerate_hid_interfaces():
            if i.vid == TARGET_VID and i.pid == TARGET_PID:
                found = True
                print(f"{i.path}\n  usage_page=0x{i.usage_page:04X} usage=0x{i.usage:02X} "
                      f"in={i.in_len} out={i.out_len} product={i.product!r}")
        if not found:
            print("未找到 VID_320F/PID_706E 设备")
        return 0

    code = 0
    for n in range(args.repeat):
        try:
            r = query_battery(handshake=args.hello)
            if args.json:
                print(_json.dumps({
                    "device": r.device, "percent": r.percent,
                    "charge_state": r.charge_state, "charge_label": r.charge_label,
                    "payload": r.payload.hex(),
                    "raw": r.raw.hex() if args.raw else None,
                }, ensure_ascii=False))
            else:
                print(f"{r.device} 电量 {r.percent}%  ({r.charge_label})")
                if args.raw:
                    print("  原始帧:", r.raw.hex(" "))
                    print("  状态块:", r.payload.hex(" "))
        except DeviceNotFound as e:
            print(f"[未连接] {e}")
            code = 2
        except (NoResponse, ProtocolError, OSError) as e:
            print(f"[读取失败] {e}")
            code = 3
        if n + 1 < args.repeat:
            time.sleep(args.interval)
    return code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
