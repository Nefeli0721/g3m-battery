"""Controlled probe tests for the G3M Pro vendor protocol.

Each test: drain, send one 64-byte output report, collect replies for ~0.6s with
timestamps. Purpose: prove whether the battery value comes from the device or is
just an echo of the request.
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


def frame(prefix, byte8=0):
    body = bytearray(64)
    body[0] = 0x04
    for i, b in enumerate(prefix):
        body[1 + i] = b
    body[8] = byte8
    return bytes(body)


def run(name, prefix, byte8=0, wait=0.6):
    drain = collect(h, 0.12)
    t0 = time.time()
    try:
        n = write_report(h, frame(prefix, byte8))
    except OSError as e:
        print("%-26s WRITE FAIL %s" % (name, e))
        return
    replies = collect(h, wait)
    print("%-26s sent=%s byte8=%02X" % (name, bytes([0x04] + prefix).hex(" "), byte8))
    if not replies:
        print("      (no reply)")
    for ts, r in replies:
        dt = (ts - t0) * 1000
        mark = ""
        if len(r) > 8:
            mark = "  [7]=%02X [8]=%02X" % (r[7], r[8])
        print("      +%6.1fms %s%s" % (dt, r[:16].hex(" "), mark))


h = open_dev()
try:
    print("=== A. echo vs device data: vary byte8 of request ===")
    run("20 00 1A 06 b8=00", [0x20, 0x00, 0x1A, 0x06], 0x00)
    run("20 00 1A 06 b8=11", [0x20, 0x00, 0x1A, 0x06], 0x11)
    run("20 00 1A 06 b8=C8", [0x20, 0x00, 0x1A, 0x06], 0xC8)
    run("20 00 1A 06 b8=34", [0x20, 0x00, 0x1A, 0x06], 0x34)

    print("\n=== B. stability: same frame 5x ===")
    for i in range(5):
        run("20 00 1A 06 #%d" % i, [0x20, 0x00, 0x1A, 0x06], 0x00, 0.4)

    print("\n=== C. does the [3][4] parameter matter? ===")
    run("20 00 00 00", [0x20, 0x00, 0x00, 0x00], 0x00)
    run("20 00 1A 00", [0x20, 0x00, 0x1A, 0x00], 0x00)
    run("20 00 00 06", [0x20, 0x00, 0x00, 0x06], 0x00)
    run("20 00 06 1A", [0x20, 0x00, 0x06, 0x1A], 0x00)
    run("20 01 1A 06", [0x20, 0x01, 0x1A, 0x06], 0x00)

    print("\n=== D. other commands with same param ===")
    run("AA 00 1A 06", [0xAA, 0x00, 0x1A, 0x06], 0x00)
    run("21 00 1A 06", [0x21, 0x00, 0x1A, 0x06], 0x00)
    run("10 00 1A 06", [0x10, 0x00, 0x1A, 0x06], 0x00)
finally:
    kernel32.CloseHandle(h)
