"""Send candidate 64-byte output reports to the vendor collection and capture replies.

Usage:
  python try_frames.py <hex64bytes | auto>

`auto` tries a set of plausible frames for the battery query and reports which
one produces a fresh reply (within 400 ms) and what it contained.
"""
import ctypes
import sys
import time
from ctypes import wintypes

kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)

GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
FILE_SHARE_READ = 0x1
FILE_SHARE_WRITE = 0x2
OPEN_EXISTING = 3
FILE_FLAG_OVERLAPPED = 0x40000000
ERROR_IO_PENDING = 997


class OVERLAPPED(ctypes.Structure):
    _fields_ = [("Internal", ctypes.c_void_p), ("InternalHigh", ctypes.c_void_p),
                ("Offset", wintypes.DWORD), ("OffsetHigh", wintypes.DWORD),
                ("hEvent", wintypes.HANDLE)]


kernel32.CreateFileW.restype = wintypes.HANDLE
kernel32.CreateFileW.argtypes = [ctypes.c_wchar_p, wintypes.DWORD, wintypes.DWORD,
                                 ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD,
                                 wintypes.HANDLE]
kernel32.CreateEventW.restype = wintypes.HANDLE
kernel32.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, ctypes.c_wchar_p]
kernel32.WriteFile.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
                               ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
kernel32.ReadFile.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
                              ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
kernel32.GetOverlappedResult.argtypes = [wintypes.HANDLE, ctypes.POINTER(OVERLAPPED),
                                         ctypes.POINTER(wintypes.DWORD), wintypes.BOOL]
kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
kernel32.CancelIoEx.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.ResetEvent.argtypes = [wintypes.HANDLE]

COL04 = (r"\\?\hid#vid_320f&pid_706e&mi_01&col04"
         r"#9&101432e6&0&0003#{4d1e55b2-f16f-11cf-88cb-001111000030}")


def open_dev():
    h = kernel32.CreateFileW(COL04, GENERIC_READ | GENERIC_WRITE,
                             FILE_SHARE_READ | FILE_SHARE_WRITE, None, OPEN_EXISTING,
                             FILE_FLAG_OVERLAPPED, None)
    if h == wintypes.HANDLE(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    return h


def write_report(h, payload):
    buf = ctypes.create_string_buffer(bytes(payload), len(payload))
    ov = OVERLAPPED()
    ev = kernel32.CreateEventW(None, True, False, None)
    ov.hEvent = ev
    written = wintypes.DWORD(0)
    ok = kernel32.WriteFile(h, buf, len(payload), ctypes.byref(written), ctypes.byref(ov))
    if not ok:
        err = ctypes.get_last_error()
        if err != ERROR_IO_PENDING:
            kernel32.CloseHandle(ev)
            raise ctypes.WinError(err)
        kernel32.WaitForSingleObject(ev, 2000)
        if not kernel32.GetOverlappedResult(h, ctypes.byref(ov), ctypes.byref(written), False):
            e = ctypes.get_last_error()
            kernel32.CloseHandle(ev)
            raise ctypes.WinError(e)
    kernel32.CloseHandle(ev)
    return written.value


def collect(h, seconds):
    out = []
    deadline = time.time() + seconds
    ev = kernel32.CreateEventW(None, True, False, None)
    while time.time() < deadline:
        buf = ctypes.create_string_buffer(256)
        ov = OVERLAPPED()
        ov.hEvent = ev
        got = wintypes.DWORD(0)
        ok = kernel32.ReadFile(h, buf, 256, ctypes.byref(got), ctypes.byref(ov))
        if not ok:
            err = ctypes.get_last_error()
            if err != ERROR_IO_PENDING:
                break
            remain = int((deadline - time.time()) * 1000)
            if remain <= 0:
                kernel32.CancelIoEx(h, ctypes.byref(ov))
                break
            w = kernel32.WaitForSingleObject(ev, min(100, remain))
            if w != 0:
                kernel32.CancelIoEx(h, ctypes.byref(ov))
                kernel32.GetOverlappedResult(h, ctypes.byref(ov), ctypes.byref(got), True)
                continue
            if not kernel32.GetOverlappedResult(h, ctypes.byref(ov), ctypes.byref(got), False):
                break
        out.append((time.time(), buf.raw[:got.value]))
    kernel32.CloseHandle(ev)
    return out


def mk(name, cmd, payload=b"", extra=None):
    body = bytes([0x04, cmd]) + payload
    body = body[:63]
    body = body + b"\x00" * (63 - len(body))
    if extra is None:
        return name, body + b"\x00"
    return name, body + bytes([extra])


def candidates():
    out = []
    # straight zeros / plain cmd echo
    for cmd in (0x20, 0xAA, 0x01, 0x02, 0x10, 0x21, 0x30, 0x0F):
        out.append(mk("cmd%02X-zero" % cmd, cmd))
    # payload patterns seen in replies
    out.append(mk("20-1A06", 0x20, bytes([0x00, 0x1A, 0x06])))
    out.append(mk("20-1A0600", 0x20, bytes([0x00, 0x1A, 0x06, 0x00])))
    out.append(mk("20-00000000", 0x20, bytes(4)))
    # checksum variants: sum / negated sum / xor over body
    for cmd in (0x20, 0xAA):
        body = bytes([0x04, cmd]) + bytes(61)
        s = sum(body) & 0xFF
        out.append(("cmd%02X-sum" % cmd, body + bytes([s])))
        out.append(("cmd%02X-negsum" % cmd, body + bytes([(0x100 - s) & 0xFF])))
        x = 0
        for b in body:
            x ^= b
        out.append(("cmd%02X-xor" % cmd, body + bytes([x])))
        # checksum over cmd..payload only (skip report id)
        s2 = sum(body[1:]) & 0xFF
        out.append(("cmd%02X-sum-no-id" % cmd, body + bytes([s2])))
        out.append(("cmd%02X-negsum-no-id" % cmd, body + bytes([(0x100 - s2) & 0xFF])))
    return out


def main():
    h = open_dev()
    try:
        # drain
        collect(h, 0.3)
        if len(sys.argv) > 1 and sys.argv[1] != "auto":
            payload = bytes.fromhex(sys.argv[1].replace(" ", ""))
            if len(payload) != 64:
                print("need exactly 64 bytes, got", len(payload))
                return
            n = write_report(h, payload)
            print("OUT:", payload.hex(" "))
            replies = collect(h, 1.0)
            for ts, r in replies:
                print("  IN :", r.hex(" "))
            return

        for name, payload in candidates():
            # drain before send so we can attribute replies
            collect(h, 0.15)
            try:
                n = write_report(h, payload)
            except OSError as e:
                print("%-22s WRITE-FAIL %s" % (name, e))
                continue
            replies = collect(h, 0.45)
            if replies:
                print("%-22s wrote=%d  replies=%d" % (name, n, len(replies)))
                for ts, r in replies:
                    print("      IN :", r.hex(" "))
            else:
                print("%-22s wrote=%d  (no reply)" % (name, n))
            time.sleep(0.15)
    finally:
        kernel32.CloseHandle(h)


if __name__ == "__main__":
    main()
