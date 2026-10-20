#!/usr/bin/env python3
"""AOA HID injector: authorize ADB on a phone whose screen/touch is dead.

Usage:
  aoa_hid.py --switch                  # 12d1 -> 18d1 (accessory mode)
  aoa_hid.py --keys tab,enter          # type a key sequence (auto-switches if needed)
  aoa_hid.py --click 777,1361          # absolute mouse click at screen coords
  aoa_hid.py --keys tab,enter --dry    # dry run: print what would be sent

Requires: pyusb (python3-usb), root/privileged container or 777 on /dev/bus/usb.
"""
import argparse
import glob
import os
import sys
import time

import usb.core
import usb.util

HUWEI_IDS = [(0x12D1, 0x107E)]
AOA_IDS = [(0x18D1, 0x2D01), (0x18D1, 0x2D00), (0x18D1, 0x2D02), (0x18D1, 0x2D03), (0x18D1, 0x2D04), (0x18D1, 0x2D05)]
ACCESSORY_SUBCLASS = 66

# --- HID descriptors (verified working) ---
KBD_BOOT = bytes([
    0x05, 0x01, 0x09, 0x06, 0xA1, 0x01, 0x05, 0x07, 0x19, 0xE0, 0x29, 0xE7, 0x15, 0x00, 0x25, 0x01,
    0x75, 0x01, 0x95, 0x08, 0x81, 0x02, 0x95, 0x01, 0x75, 0x08, 0x81, 0x01, 0x95, 0x05, 0x75, 0x01,
    0x05, 0x08, 0x19, 0x01, 0x29, 0x05, 0x91, 0x02, 0x95, 0x01, 0x75, 0x03, 0x91, 0x01, 0x95, 0x06,
    0x75, 0x08, 0x15, 0x00, 0x25, 0x65, 0x05, 0x07, 0x19, 0x00, 0x29, 0x65, 0x81, 0x00, 0xC0,
])
MOUSE_ABS = bytes([
    0x05, 0x01, 0x09, 0x02, 0xA1, 0x01, 0x09, 0x01, 0xA1, 0x00, 0x05, 0x09, 0x19, 0x01, 0x29, 0x05,
    0x15, 0x00, 0x25, 0x01, 0x95, 0x05, 0x75, 0x01, 0x81, 0x02, 0x95, 0x01, 0x75, 0x03, 0x81, 0x01,
    0x05, 0x01, 0x09, 0x30, 0x09, 0x31, 0x16, 0x00, 0x00, 0x26, 0xFF, 0x7F, 0x75, 0x10, 0x95, 0x02,
    0x81, 0x02, 0xC0, 0xC0,
])
MOUSE_REL = bytes([
    0x05, 0x01, 0x09, 0x02, 0xA1, 0x01, 0x09, 0x01, 0xA1, 0x00, 0x05, 0x09, 0x19, 0x01, 0x29, 0x05,
    0x15, 0x00, 0x25, 0x01, 0x95, 0x05, 0x75, 0x01, 0x81, 0x02, 0x95, 0x01, 0x75, 0x03, 0x81, 0x01,
    0x05, 0x01, 0x09, 0x30, 0x09, 0x31, 0x09, 0x38, 0x15, 0x81, 0x25, 0x7F, 0x75, 0x08, 0x95, 0x03,
    0x81, 0x06, 0x05, 0x0C, 0x0A, 0x38, 0x02, 0x15, 0x81, 0x25, 0x7F, 0x75, 0x08, 0x95, 0x01, 0x81,
    0x06, 0xC0, 0xC0,
])
CONSUMER = bytes([
    0x05, 0x0C, 0x09, 0x01, 0xA1, 0x01, 0x15, 0x00, 0x26, 0xFF, 0x03, 0x19, 0x00, 0x2A, 0xFF, 0x03,
    0x75, 0x10, 0x95, 0x01, 0x81, 0x00, 0xC0,
])

KEYS = {
    "enter": 0x28, "tab": 0x2B, "space": 0x2C, "esc": 0x29, "backspace": 0x2A,
    "up": 0x52, "down": 0x51, "left": 0x50, "right": 0x4F,
    "home": 0x4A, "menu": 0x65, "power": 0x66,
}

# AOA control requests
REQ_GET_PROTOCOL, REQ_SEND_STRING, REQ_START = 51, 52, 53
REQ_REGISTER_HID, REQ_UNREGISTER_HID, REQ_SET_HID_DESC, REQ_SEND_EVENT = 54, 55, 56, 57


def fix_perms():
    for p in glob.glob("/dev/bus/usb/*/*"):
        try:
            os.chmod(p, 0o777)
        except OSError:
            pass


def find_first(ids):
    for vid, pid in ids:
        d = usb.core.find(idVendor=vid, idProduct=pid)
        if d:
            return d
    return None


def accessory_iface(dev):
    for cfg in dev:
        for intf in cfg:
            if intf.bInterfaceSubClass == ACCESSORY_SUBCLASS:
                return intf
    return None


def switch_to_accessory(timeout=20.0, serial=b""):
    """12d1:107e -> 18d1:2d01. Returns the new device handle or None."""
    fix_perms()
    dev = find_first(AOA_IDS)
    if dev:
        print("[=] already in accessory mode")
        return dev
    dev = find_first(HUWEI_IDS)
    if not dev:
        print("[!] no device found on USB")
        return None
    try:
        proto = int.from_bytes(bytes(dev.ctrl_transfer(0xC0, REQ_GET_PROTOCOL, 0, 0, 2, timeout=2000)), "little")
        print(f"[=] AOA protocol version: {proto}")
    except usb.core.USBError as e:
        print(f"[!] GET_PROTOCOL failed: {e}")
        return None
    for idx, s in enumerate([b"hid", b"phone", b"hid", b"1.0", b"", serial]):
        try:
            dev.ctrl_transfer(0x40, REQ_SEND_STRING, 0, idx, s + b"\0", timeout=2000)
        except usb.core.USBError as e:
            print(f"[!] SEND_STRING[{idx}] failed: {e}")
    try:
        dev.ctrl_transfer(0x40, REQ_START, 0, 0, b"", timeout=3000)
        print("[=] START sent")
    except usb.core.USBError as e:
        print(f"[!] START failed: {e}")
    usb.util.dispose_resources(dev)
    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(0.5)
        fix_perms()
        d = find_first(AOA_IDS)
        if d:
            print(f"[+] re-enumerated as {d.idVendor:04x}:{d.idProduct:04x}")
            return d
    print("[!] timeout waiting for accessory mode")
    return None


def claim(dev):
    intf = accessory_iface(dev)
    if intf is None:
        print("[!] no accessory interface (subclass 66)")
        return None, None
    try:
        usb.util.claim_interface(dev, intf.bInterfaceNumber)
    except usb.core.USBError as e:
        print(f"[~] claim_interface: {e} (continuing, usbfs is shared)")
    return intf, intf.bInterfaceNumber


def clear_halt(dev, intf):
    for ep in (intf[0], intf[1] if len(intf) > 1 else None):
        if ep is None:
            continue
        try:
            dev.clear_halt(ep)
        except usb.core.USBError:
            pass


def ctrl(dev, req, value, index, data=b"", timeout=3000):
    try:
        return dev.ctrl_transfer(0x40, req, value, index, data, timeout=timeout)
    except usb.core.USBError as e:
        print(f"[!] req {req} STALL/ERR: {e}")
        return None


def register_hid(dev, hid_id, desc):
    """REGISTER_HID: wValue=hid_id, wIndex=DESCRIPTOR LENGTH, wLength=0 (critical!)"""
    r = ctrl(dev, REQ_REGISTER_HID, hid_id, len(desc))
    if r is None:
        return False
    r2 = ctrl(dev, REQ_SET_HID_DESC, hid_id, 0, desc)
    if r2 is None:
        return False
    print(f"[+] HID {hid_id} registered, descriptor {r2}B")
    time.sleep(0.4)  # let the kernel workqueue run acc_hid_init()
    return True


def send_event(dev, hid_id, report):
    return ctrl(dev, REQ_SEND_EVENT, hid_id, 0, report, timeout=2000)


def type_keys(dev, combo, hid_id=1, gap=0.30):
    if not register_hid(dev, hid_id, KBD_BOOT):
        return False
    for i, name in enumerate(combo, 1):
        code = KEYS.get(name)
        if code is None:
            print(f"[!] unknown key '{name}'")
            return False
        if send_event(dev, hid_id, bytes([0, 0, code, 0, 0, 0, 0, 0])) is None:
            return False
        time.sleep(0.10)
        send_event(dev, hid_id, bytes(8))  # release
        print(f"[>] {i}/{len(combo)} {name}")
        time.sleep(gap)
    return True


def click(dev, x, y, screen=(1080, 2312), hid_id=2):
    if not register_hid(dev, hid_id, MOUSE_ABS):
        return False
    sx = int(x / screen[0] * 0x7FFF)
    sy = int(y / screen[1] * 0x7FFF)
    for btn in (0, 1, 0):
        send_event(dev, hid_id, bytes([btn, (sx >> 8) & 0xFF, sx & 0xFF, (sy >> 8) & 0xFF, sy & 0xFF]))
        time.sleep(0.15 if btn else 0.25)
    print(f"[>] click ({x},{y}) -> raw ({sx},{sy})")
    return True


def click_rel(dev, dx, dy, hid_id=2, steps=1):
    """Relative pointer move + click. Some devices ignore absolute coords."""
    if not register_hid(dev, hid_id, MOUSE_REL):
        return False
    for _ in range(max(1, steps)):
        dx1 = max(-127, min(127, dx))
        dy1 = max(-127, min(127, dy))
        send_event(dev, hid_id, bytes([0, dx1 & 0xFF, dy1 & 0xFF, 0]))
        time.sleep(0.05)
        dx -= dx1
        dy -= dy1
        if dx == 0 and dy == 0:
            break
    for btn in (0, 1, 0):
        send_event(dev, hid_id, bytes([btn, 0, 0, 0]))
        time.sleep(0.15 if btn else 0.25)
    print("[>] rel click")
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--switch", action="store_true", help="only switch to accessory mode")
    ap.add_argument("--keys", help="comma list: tab,enter / down,enter ...")
    ap.add_argument("--click", help="x,y in screen pixels (absolute pointer)")
    ap.add_argument("--click-rel", help="dx,dy relative pointer move + click")
    ap.add_argument("--screen", default="1080,2312")
    ap.add_argument("--hid-id", type=int, default=1)
    ap.add_argument("--serial", default=os.environ.get("AOA_SERIAL", ""), help="serial string reported to the device (manufacturer card)")
    ap.add_argument("--no-switch", action="store_true", help="assume already 18d1")
    ap.add_argument("--dry", action="store_true")

    args = ap.parse_args()

    if args.dry:
        print(f"would send: keys={args.keys} click={args.click} rel={args.click_rel} switch={not args.no_switch}")
        return 0

    dev = find_first(AOA_IDS) if args.no_switch else switch_to_accessory(serial=args.serial.encode())
    if not dev:
        return 2
    if args.switch:
        return 0

    intf, _ = claim(dev)
    if intf is None:
        return 3
    clear_halt(dev, intf)

    ok = True
    if args.keys:
        ok = type_keys(dev, args.keys.split(","), hid_id=args.hid_id)
    if args.click:
        x, y = (int(v) for v in args.click.split(","))
        sw, sh = (int(v) for v in args.screen.split(","))
        ok = click(dev, x, y, (sw, sh), hid_id=args.hid_id + 1) and ok
    if args.click_rel:
        dx, dy = (int(v) for v in args.click_rel.split(","))
        ok = click_rel(dev, dx, dy, hid_id=args.hid_id + 1) and ok
    usb.util.dispose_resources(dev)
    return 0 if ok else 4


if __name__ == "__main__":
    sys.exit(main())
