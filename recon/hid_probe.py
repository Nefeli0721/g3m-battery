"""HID probe for the vendor config collection (COL04).

Modes:
  read [seconds]            passively read 64-byte input reports
  send <hex bytes> [rep]    write one output report, then read replies
  both <hex> [seconds]      send then read

Uses overlapped I/O so reads can time out. stdlib ctypes only.
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
kernel32.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL,
                                  ctypes.c_wchar_p]
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


def open_handle(path, write=True):
    acc = GENERIC_READ | (GENERIC_WRITE if write else 0)
    h = kernel32.CreateFileW(path, acc, FILE_SHARE_READ | FILE_SHARE_WRITE, None,
                             OPEN_EXISTING, FILE_FLAG_OVERLAPPED, None)
    if h == wintypes.HANDLE(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    return h


def send_report(h, payload, wait_ms=2000):
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
        kernel32.WaitForSingleObject(ev, wait_ms)
        if not kernel32.GetOverlappedResult(h, ctypes.byref(ov), ctypes.byref(written), False):
            err = ctypes.get_last_error()
            kernel32.CloseHandle(ev)
            raise ctypes.WinError(err)
    kernel32.CloseHandle(ev)
    return written.value


def read_reports(h, seconds, quiet=True):
    reports = []
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
            w = kernel32.WaitForSingleObject(ev, min(250, remain))
            if w != 0:  # timed out
                kernel32.CancelIoEx(h, ctypes.byref(ov))
                kernel32.GetOverlappedResult(h, ctypes.byref(ov), ctypes.byref(got), True)
                continue
            ok = kernel32.GetOverlappedResult(h, ctypes.byref(ov), ctypes.byref(got), False)
            if not ok:
                break
        data = buf.raw[:got.value]
        reports.append(data)
        print("IN  %s  len=%d  %s" % (time.strftime("%H:%M:%S"), len(data),
                                      " ".join("%02X" % b for b in data)))
        if not quiet:
            pass
        # small pause to avoid spin
        time.sleep(0.001)
    kernel32.CloseHandle(ev)
    return reports


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    mode = sys.argv[1]
    path = COL04
    if mode == "read":
        secs = float(sys.argv[2]) if len(sys.argv) > 2 else 5
        h = open_handle(path, write=False)
        try:
            print("passive read %ss ..." % secs)
            read_reports(h, secs)
        finally:
            kernel32.CloseHandle(h)
    elif mode == "send":
        payload = bytes.fromhex(sys.argv[2].replace(" ", ""))
        h = open_handle(path)
        try:
            n = send_report(h, payload)
            print("OUT", " ".join("%02X" % b for b in payload), "-> wrote", n)
            read_reports(h, 3)
        finally:
            kernel32.CloseHandle(h)
    elif mode == "both":
        payload = bytes.fromhex(sys.argv[2].replace(" ", ""))
        secs = float(sys.argv[3]) if len(sys.argv) > 3 else 5
        h = open_handle(path)
        try:
            n = send_report(h, payload)
            print("OUT", " ".join("%02X" % b for b in payload), "-> wrote", n)
            read_reports(h, secs)
        finally:
            kernel32.CloseHandle(h)
    else:
        print("unknown mode", mode)


if __name__ == "__main__":
    main()
