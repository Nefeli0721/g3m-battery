"""Enumerate HID devices, print product strings and full report descriptors.

Pure stdlib ctypes: setupapi + hid + kernel32. No pip packages required.
"""
import ctypes
from ctypes import wintypes

setupapi = ctypes.WinDLL('setupapi', use_last_error=True)
hid = ctypes.WinDLL('hid', use_last_error=True)
kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)

DIGCF_PRESENT = 0x02
DIGCF_DEVICEINTERFACE = 0x10
INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value
IOCTL_HID_GET_REPORT_DESCRIPTOR = 0x000B0000
IOCTL_HID_GET_INDEXED_STRING = 0x000B0020
GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
FILE_SHARE_READ = 0x1
FILE_SHARE_WRITE = 0x2
OPEN_EXISTING = 3
FILE_FLAG_OVERLAPPED = 0x40000000


class GUID(ctypes.Structure):
    _fields_ = [("Data1", ctypes.c_uint32), ("Data2", ctypes.c_uint16),
                ("Data3", ctypes.c_uint16), ("Data4", ctypes.c_ubyte * 8)]


class SP_DEVICE_INTERFACE_DATA(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("InterfaceClassGuid", GUID),
                ("Flags", wintypes.DWORD), ("Reserved", ctypes.c_void_p)]


class SP_DEVICE_INTERFACE_DETAIL_DATA_W(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("DevicePath", ctypes.c_wchar * 1024)]


class HIDD_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("Size", ctypes.c_ulong), ("VendorID", ctypes.c_ushort),
                ("ProductID", ctypes.c_ushort), ("VersionNumber", ctypes.c_ushort)]


setupapi.SetupDiGetClassDevsW.restype = wintypes.HANDLE
setupapi.SetupDiGetClassDevsW.argtypes = [ctypes.POINTER(GUID), ctypes.c_wchar_p,
                                          ctypes.c_void_p, wintypes.DWORD]
setupapi.SetupDiEnumDeviceInterfaces.argtypes = [wintypes.HANDLE, ctypes.c_void_p,
                                                 ctypes.POINTER(GUID), wintypes.DWORD,
                                                 ctypes.POINTER(SP_DEVICE_INTERFACE_DATA)]
setupapi.SetupDiGetDeviceInterfaceDetailW.argtypes = [
    wintypes.HANDLE, ctypes.POINTER(SP_DEVICE_INTERFACE_DATA), ctypes.c_void_p,
    wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
setupapi.SetupDiDestroyDeviceInfoList.argtypes = [wintypes.HANDLE]

hid.HidD_GetAttributes.argtypes = [wintypes.HANDLE, ctypes.POINTER(HIDD_ATTRIBUTES)]
hid.HidD_GetProductString.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.ULONG]
hid.HidD_GetManufacturerString.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.ULONG]
hid.HidD_GetSerialNumberString.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.ULONG]

kernel32.CreateFileW.restype = wintypes.HANDLE
kernel32.CreateFileW.argtypes = [ctypes.c_wchar_p, wintypes.DWORD, wintypes.DWORD,
                                 ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD,
                                 wintypes.HANDLE]
kernel32.DeviceIoControl.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p,
                                     wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
                                     ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]


def open_path(path):
    return kernel32.CreateFileW(path, GENERIC_READ | GENERIC_WRITE,
                                FILE_SHARE_READ | FILE_SHARE_WRITE, None,
                                OPEN_EXISTING, 0, None)


def hid_string(h, getter):
    buf = ctypes.create_unicode_buffer(256)
    if getter(h, buf, ctypes.sizeof(buf)):
        return buf.value
    return ""


def get_descriptor(h):
    buf = ctypes.create_string_buffer(4096)
    got = wintypes.DWORD(0)
    ok = kernel32.DeviceIoControl(h, IOCTL_HID_GET_REPORT_DESCRIPTOR, None, 0,
                                  buf, ctypes.sizeof(buf), ctypes.byref(got), None)
    if not ok:
        return None
    return buf.raw[:got.value]


def enumerate_hid():
    """Yield dicts for every HID interface."""
    guid = GUID()
    hid_guid_str = "{4d1e55b2-f16f-11cf-88cb-001111000030}"
    ctypes.windll.ole32.CLSIDFromString(hid_guid_str, ctypes.byref(guid))

    devs = setupapi.SetupDiGetClassDevsW(ctypes.byref(guid), None, None,
                                         DIGCF_PRESENT | DIGCF_DEVICEINTERFACE)
    if devs == INVALID_HANDLE_VALUE:
        raise ctypes.WinError(ctypes.get_last_error())

    out = []
    idx = 0
    while True:
        did = SP_DEVICE_INTERFACE_DATA()
        did.cbSize = ctypes.sizeof(did)
        if not setupapi.SetupDiEnumDeviceInterfaces(devs, None, ctypes.byref(guid),
                                                    idx, ctypes.byref(did)):
            break
        idx += 1
        need = wintypes.DWORD(0)
        setupapi.SetupDiGetDeviceInterfaceDetailW(devs, ctypes.byref(did), None, 0,
                                                  ctypes.byref(need), None)
        if not need.value:
            continue
        detail = SP_DEVICE_INTERFACE_DETAIL_DATA_W()
        detail.cbSize = 8 if ctypes.sizeof(ctypes.c_void_p) == 8 else 5
        detail_buf = ctypes.create_string_buffer(need.value)
        ctypes.cast(detail_buf, ctypes.POINTER(wintypes.DWORD))[0] = detail.cbSize
        if not setupapi.SetupDiGetDeviceInterfaceDetailW(
                devs, ctypes.byref(did), detail_buf, need.value,
                ctypes.byref(need), None):
            continue
        path = ctypes.wstring_at(ctypes.addressof(detail_buf) + 4)
        h = open_path(path)
        if h == INVALID_HANDLE_VALUE:
            out.append({"path": path, "error": ctypes.get_last_error()})
            continue
        try:
            attr = HIDD_ATTRIBUTES()
            attr.Size = ctypes.sizeof(attr)
            info = {"path": path}
            if hid.HidD_GetAttributes(h, ctypes.byref(attr)):
                info.update(vid=attr.VendorID, pid=attr.ProductID,
                            version=attr.VersionNumber)
            info["product"] = hid_string(h, hid.HidD_GetProductString)
            info["manufacturer"] = hid_string(h, hid.HidD_GetManufacturerString)
            info["serial"] = hid_string(h, hid.HidD_GetSerialNumberString)
            info["descriptor"] = get_descriptor(h)
            out.append(info)
        finally:
            kernel32.CloseHandle(h)

    setupapi.SetupDiDestroyDeviceInfoList(devs)
    return out


if __name__ == "__main__":
    import sys

    target_vid = None
    target_pid = None
    if len(sys.argv) >= 3:
        target_vid = int(sys.argv[1], 0)
        target_pid = int(sys.argv[2], 0)

    for d in enumerate_hid():
        if "error" in d:
            print("ERR", d["path"], d["error"])
            continue
        if target_vid is not None and (d.get("vid") != target_vid or d.get("pid") != target_pid):
            continue
        print("=" * 100)
        print("PATH      :", d["path"])
        print("VID/PID   : %04X:%04X  ver=%04X" % (d.get("vid", 0), d.get("pid", 0), d.get("version", 0)))
        print("PRODUCT   :", d.get("product"))
        print("MFR       :", d.get("manufacturer"))
        print("SERIAL    :", d.get("serial"))
        desc = d.get("descriptor")
        if desc:
            print("DESCRIPTOR (%d bytes):" % len(desc))
            for i in range(0, len(desc), 16):
                chunk = desc[i:i + 16]
                print("  %03X: %s  |%s|" % (
                    i,
                    " ".join("%02X" % b for b in chunk),
                    "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)))
        else:
            print("DESCRIPTOR: <unavailable>")
