"""HID report descriptor + caps dumper (stdlib ctypes only).

Reads full USB HID report descriptors via IOCTL_HID_GET_REPORT_DESCRIPTOR and
prints parsed top-level collections with usage pages, plus HidP_GetCaps report
lengths (input/output/feature).
"""
import ctypes
import sys
from ctypes import wintypes

setupapi = ctypes.WinDLL('setupapi', use_last_error=True)
hid = ctypes.WinDLL('hid', use_last_error=True)
kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
ole32 = ctypes.windll.ole32

DIGCF_PRESENT = 0x02
DIGCF_DEVICEINTERFACE = 0x10
INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value
IOCTL_HID_GET_REPORT_DESCRIPTOR = 0x000B0000
GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
FILE_SHARE_READ = 0x1
FILE_SHARE_WRITE = 0x2
OPEN_EXISTING = 3


class GUID(ctypes.Structure):
    _fields_ = [("Data1", ctypes.c_uint32), ("Data2", ctypes.c_uint16),
                ("Data3", ctypes.c_uint16), ("Data4", ctypes.c_ubyte * 8)]


class SP_DEVICE_INTERFACE_DATA(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("InterfaceClassGuid", GUID),
                ("Flags", wintypes.DWORD), ("Reserved", ctypes.c_void_p)]


class HIDD_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("Size", ctypes.c_ulong), ("VendorID", ctypes.c_ushort),
                ("ProductID", ctypes.c_ushort), ("VersionNumber", ctypes.c_ushort)]


class HIDP_CAPS(ctypes.Structure):
    _fields_ = [
        ("Usage", ctypes.c_ushort), ("UsagePage", ctypes.c_ushort),
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
hid.HidD_GetPreparsedData.argtypes = [wintypes.HANDLE, ctypes.POINTER(ctypes.c_void_p)]
hid.HidD_FreePreparsedData.argtypes = [ctypes.c_void_p]
hid.HidP_GetCaps.argtypes = [ctypes.c_void_p, ctypes.POINTER(HIDP_CAPS)]
kernel32.CreateFileW.restype = wintypes.HANDLE
kernel32.CreateFileW.argtypes = [ctypes.c_wchar_p, wintypes.DWORD, wintypes.DWORD,
                                 ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD,
                                 wintypes.HANDLE]
kernel32.DeviceIoControl.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p,
                                     wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
                                     ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

USAGE_PAGES = {
    0x01: "Generic Desktop", 0x02: "Simulation", 0x05: "Game Controls",
    0x06: "Generic Device", 0x07: "Keyboard", 0x08: "LED", 0x09: "Button",
    0x0C: "Consumer", 0x0D: "Digitizer", 0x0F: "PID", 0x10: "Unicode",
    0x14: "Alphanumeric", 0xFF00: "Vendor 0xFF00", 0xFF01: "Vendor 0xFF01",
    0xFF0C: "Vendor 0xFF0C", 0xFFBC: "Vendor 0xFFBC",
}
USAGES = {
    (0x06, 0x20): "Battery Strength",
    (0x01, 0x06): "Keyboard",
    (0x01, 0x02): "Mouse",
    (0x01, 0x80): "System Control",
    (0x0C, 0x01): "Consumer Control",
    (0x06, 0x01): "Generic Device Controls",
}


def open_hid(path, access=GENERIC_READ | GENERIC_WRITE):
    return kernel32.CreateFileW(path, access, FILE_SHARE_READ | FILE_SHARE_WRITE,
                                None, OPEN_EXISTING, 0, None)


def hid_string(h, getter):
    buf = ctypes.create_unicode_buffer(256)
    if getter(h, buf, ctypes.sizeof(buf)):
        return buf.value
    return ""


def parse_descriptor(desc):
    """Minimal HID item parser -> list of (offset, kind, payload)."""
    items = []
    i = 0
    n = len(desc)
    while i < n:
        b = desc[i]
        if b == 0xFE:  # long item
            size = desc[i + 1] if i + 1 < n else 0
            tag = desc[i + 2] if i + 2 < n else 0
            items.append((i, ("long", tag, desc[i + 3:i + 3 + size])))
            i += 3 + size
            continue
        size = [0, 1, 2, 4][b & 0x03]
        itype = (b >> 2) & 0x03
        tag = b >> 4
        data = desc[i + 1:i + 1 + size]
        val = int.from_bytes(data, "little") if data else None
        items.append((i, (itype, tag, val, size)))
        i += 1 + size
    return items


def describe(desc):
    lines = []
    usage_page = None
    depth = 0
    for off, item in parse_descriptor(desc):
        if item[0] == "long":
            lines.append("  %03X: LONG %s" % (off, item[2].hex()))
            continue
        itype, tag, val, size = item
        # Main items
        if itype == 0:
            if tag == 0x8:  # Input
                lines.append("  %03X: %sINPUT    flags=%s" % (off, "  " * depth, "%08b" % val))
            elif tag == 0x9:  # Output
                lines.append("  %03X: %sOUTPUT   flags=%s" % (off, "  " * depth, "%08b" % val))
            elif tag == 0xB:  # Feature
                lines.append("  %03X: %sFEATURE  flags=%s" % (off, "  " * depth, "%08b" % val))
            elif tag == 0xA:  # Collection
                lines.append("  %03X: %sCOLLECTION %s" % (off, "  " * depth,
                                                           {0: "Physical", 1: "Application",
                                                            2: "Logical", 3: "Report"}.get(val, val)))
            elif tag == 0xC:  # End Collection
                depth = max(0, depth - 1)
                lines.append("  %03X: %sEND_COLLECTION" % (off, "  " * depth))
        elif itype == 1:
            if tag == 0x0:
                usage_page = val
                lines.append("  %03X: USAGE_PAGE 0x%04X %s" % (
                    off, val, USAGE_PAGES.get(val, "")))
            elif tag == 0x1:  # Usage
                u = val & 0xFFFF
                lines.append("  %03X: USAGE 0x%04X %s" % (
                    off, u, USAGES.get((usage_page, u), "")))
            elif tag == 0x2:
                lines.append("  %03X: USAGE_MIN 0x%04X" % (off, val))
            elif tag == 0x3:
                lines.append("  %03X: USAGE_MAX 0x%04X" % (off, val))
        elif itype == 2:
            if tag == 0x1:
                lines.append("  %03X: REPORT_ID %d" % (off, val))
            elif tag == 0x7:
                lines.append("  %03X: REPORT_SIZE %d" % (off, val))
            elif tag == 0x8:
                lines.append("  %03X: REPORT_COUNT %d" % (off, val))
            elif tag == 0x9:
                lines.append("  %03X: PUSH/POP" % off)
    return lines


def enumerate_hid():
    guid = GUID()
    ole32.CLSIDFromString("{4d1e55b2-f16f-11cf-88cb-001111000030}", ctypes.byref(guid))
    devs = setupapi.SetupDiGetClassDevsW(ctypes.byref(guid), None, None,
                                         DIGCF_PRESENT | DIGCF_DEVICEINTERFACE)
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
        buf = ctypes.create_string_buffer(need.value)
        ctypes.cast(buf, ctypes.POINTER(wintypes.DWORD))[0] = 8
        if not setupapi.SetupDiGetDeviceInterfaceDetailW(
                devs, ctypes.byref(did), buf, need.value, ctypes.byref(need), None):
            continue
        path = ctypes.wstring_at(ctypes.addressof(buf) + 4)
        d = {"path": path}
        h = open_hid(path)
        access = "rw"
        if h == INVALID_HANDLE_VALUE:
            h = open_hid(path, 0)
            access = "none"
        if h == INVALID_HANDLE_VALUE:
            out.append(dict(d, err=ctypes.get_last_error()))
            continue
        try:
            d["access"] = access
            attr = HIDD_ATTRIBUTES()
            attr.Size = ctypes.sizeof(attr)
            if hid.HidD_GetAttributes(h, ctypes.byref(attr)):
                d["vid"], d["pid"], d["ver"] = attr.VendorID, attr.ProductID, attr.VersionNumber
            d["product"] = hid_string(h, hid.HidD_GetProductString)
            d["mfr"] = hid_string(h, hid.HidD_GetManufacturerString)

            prep = ctypes.c_void_p()
            if hid.HidD_GetPreparsedData(h, ctypes.byref(prep)):
                caps = HIDP_CAPS()
                if hid.HidP_GetCaps(prep, ctypes.byref(caps)) == 0x00110000:  # HIDP_STATUS_SUCCESS
                    d["caps"] = dict(usage=caps.Usage, usage_page=caps.UsagePage,
                                     in_len=caps.InputReportByteLength,
                                     out_len=caps.OutputReportByteLength,
                                     feat_len=caps.FeatureReportByteLength)
                hid.HidD_FreePreparsedData(prep)

            obuf = ctypes.create_string_buffer(8192)
            got = wintypes.DWORD(0)
            ok = kernel32.DeviceIoControl(h, IOCTL_HID_GET_REPORT_DESCRIPTOR, None, 0,
                                          obuf, ctypes.sizeof(obuf),
                                          ctypes.byref(got), None)
            if ok:
                d["descriptor"] = obuf.raw[:got.value]
            else:
                d["desc_err"] = ctypes.get_last_error()
        finally:
            kernel32.CloseHandle(h)
        out.append(d)
    setupapi.SetupDiDestroyDeviceInfoList(devs)
    return out


def main():
    vid = int(sys.argv[1], 0) if len(sys.argv) > 1 else None
    pid = int(sys.argv[2], 0) if len(sys.argv) > 2 else None
    for d in enumerate_hid():
        if d.get("vid") is None:
            continue
        if vid is not None and (d["vid"] != vid or d["pid"] != pid):
            continue
        print("=" * 100)
        print("PATH   :", d["path"])
        print("VID:PID: %04X:%04X ver=%04X access=%s" % (d["vid"], d["pid"], d["ver"], d.get("access")))
        print("PRODUCT:", d.get("product"), "| MFR:", d.get("mfr"))
        print("CAPS   :", d.get("caps"))
        if "desc_err" in d:
            print("DESC ERR: %s" % d["desc_err"])
        desc = d.get("descriptor")
        if desc:
            print("--- report descriptor (%d bytes) ---" % len(desc))
            for line in describe(desc):
                print(line)


if __name__ == "__main__":
    main()
