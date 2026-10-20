---
name: adb-aoa-hid
description: Authorize ADB/USB debugging on an Android device whose screen or touch does not work, by injecting HID keyboard and mouse events over AOA (Android Open Accessory) mode instead of tapping the "Allow USB debugging" dialog. Also covers enabling, verifying and restoring wireless adb (adb tcpip 5555). Use when adb reports `unauthorized`, when the RSA-fingerprint dialog cannot be tapped, when the digitiser or display is broken, when no OTG adapter is available, or when wireless debugging must survive a reboot without any user interaction.
---

# ADB authorization via AOA HID injection

Goal: turn `<serial> unauthorized` into `<serial> device` on a phone nobody can touch.

AOA HID works at the USB control-transfer level, so it bypasses the touchscreen entirely.
It does **not** bypass the authorization dialog — it *presses* it for you.

## Prerequisites

- Linux host with the phone on USB, `pyusb` (`python3-usb`), `adb` (platform-tools).
- Write access to `/dev/bus/usb/*/*` — run in a privileged container, or `chmod 777` each node
  after every re-enumeration of the device.
- `uhubctl` on a controllable hub is helpful but optional (used to power-cycle the port).
- For USB enumeration, node permissions and the Wi-Fi link itself, use the **`adb-connect`** skill
  (`bash scripts/adb_connect.sh status|usb|perms|wifi`). This skill only covers the authorization.

## Workflow

1. **Free the interface.** `adb kill-server` — an adb server holding the accessory interface
   makes every pyusb write fail or STALL.
2. **Switch to accessory mode** (vendor `12d1` → `18d1`):
   ```bash
   python3 scripts/aoa_hid.py --switch
   ```
   This sends GET_PROTOCOL, six SEND_STRINGs and START, then re-`find()`s the device.
   The old handle dies on re-enumeration — never reuse it.
3. **Inject the confirmation keys:**
   ```bash
   python3 scripts/aoa_hid.py --keys tab,enter
   ```
   `tab,enter` is the winning sequence: on EMUI the "always allow this computer" checkbox
   starts focused, so one TAB reaches 确定/Allow and ENTER activates it. Use `space` only if
   you deliberately want to toggle the checkbox.

   **Mouse fallback.** If the dialog ignores keys (custom focus order, non-focusable buttons),
   click it by coordinates instead:
   ```bash
   adb shell uiautomator dump /sdcard/w.xml && adb shell cat /sdcard/w.xml   # read bounds
   python3 scripts/aoa_hid.py --click 777,1361        # absolute pointer (default 1080x2312)
   python3 scripts/aoa_hid.py --click 777,1361 --screen 1080,2400
   python3 scripts/aoa_hid.py --click-rel 40,-30      # relative nudge, then click
   ```
   Absolute mode maps screen pixels onto 0..0x7FFF, so pass the real screen size. Tap the
   "always allow" checkbox first, then the confirm button — that is (540,1205) then (777,1361)
   on a 1080x2312 EMUI dialog.
4. **Wait, do not interrupt.** Check `adb devices` every 3s for ~15s. A successful round
   shows `authorizing`, then briefly `absent` (adbd restarting), then `device`.
   `kill-server` during that window throws the result away.
5. **Automate the retry** when the first attempt misses:
   ```bash
   bash scripts/autohit.sh [serial] [adb-path]
   ```
   It cycles key combinations, one `kill-server` + inject + query per round, and exits 0 on
   `device`.
6. **Lock it in:**
   ```bash
   adb tcpip 5555
   adb connect <phone-ip>:5555
   ```

## Verify the authorization is permanent

`/data/misc/adb/adb_keys` is unreadable to `shell` (`system:shell 640`), so test behaviourally:
power-cycle the hub port (equivalent to unplugging), wait for re-enumeration, then
`adb kill-server && adb devices`. `device` with no dialog means the public key is written.

## Pitfalls

- **`REGISTER_HID` parameters**: `wValue=hid_id`, `wIndex=descriptor length`, `wLength=0`.
  Passing the length as `wLength` STALLs even on devices advertising AOA protocol 2.
- The HID device is only created after `SET_HID_REPORT_DESC` has delivered exactly
  `wIndex` bytes. Short or long sends silently produce a dead HID device.
- `adb devices` showing `authorizing` is an adb-server state, not evidence of a click.
- The power key is a useless probe: it does not change USB state.
- Endpoint halts recover with `dev.clear_halt(ep)`; a power cycle does not clear them.
- Multiple keys, a USB hub, or a 10s power cycle all cost 20-30s per attempt — budget for it.
- `adb tcpip 5555` does not persist across reboot and `persist.adb.tcp.port` is refused for
  `shell`. Android 10 has no wireless-debugging pairing. After a reboot, USB is already
  authorized: plug in and re-run `adb tcpip 5555`.

## Safety

- Only run this on hardware you own or are explicitly authorized to service. HID injection is
  equivalent to typing on the device — it can unlock, tap through prompts and approve anything,
  not just the debugging dialog.
- Ticking "always allow" writes the host key into `/data/misc/adb/adb_keys` **permanently**.
  On a phone whose screen is dead it cannot be revoked from the device.
- `adb tcpip 5555` exposes the phone to every host on the LAN; any of them can trigger the
  dialog and, if approved, become permanently trusted. Close it with `adb usb` when done.
- Unplugging the cable leaves accessory mode and returns the phone to normal USB behaviour.

## Reference

Protocol tables, descriptor hex dumps, dialog coordinates, ADB header format and the
failure-mode table: [references/aoa-protocol.md](references/aoa-protocol.md).
