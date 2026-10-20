# AOA / ADB protocol reference (field-verified)

## AOA control requests (bmRequestType 0x40 = vendor, host→device)

| # | Request | wValue | wIndex | wLength | Notes |
|---|---|---|---|---|---|
| 51 | GET_PROTOCOL | 0 | 0 | 2 | bmRequestType **0xC0**; returns LE u16 (2 = HID supported) |
| 52 | SEND_STRING | 0 | 0=manufacturer 1=model 2=description 3=version 4=URI 5=serial | len | string must be NUL-terminated |
| 53 | START | 0 | 0 | 0 | device re-enumerates (12d1→18d1), old handle dies |
| 54 | REGISTER_HID | **hid_id** | **descriptor length** | **0** | ← the #1 gotcha, see below |
| 55 | UNREGISTER_HID | hid_id | 0 | 0 | |
| 56 | SET_HID_REPORT_DESC | hid_id | 0 | desc length | send the bytes as data |
| 57 | SEND_HID_EVENT | hid_id | 0 | report length | report bytes as data |
| 58 | SET_AUDIO_MODE | mode | 0 | 0 | unused |
| 59/60 | START_AUDIO / STOP_AUDIO | 0 | 0 | 0 | unused |

### The gotcha that cost 8 hours

`REGISTER_HID` with `wIndex=0|1` and `wLength=desc_len` → **EPIPE/STALL every time**,
even though the device reports protocol v2.

Correct form (matches scrcpy `app/src/usb/aoa_hid.c`):

```python
dev.ctrl_transfer(0x40, 54, hid_id, len(desc), b"", timeout=3000)   # wIndex = LENGTH, wLength = 0
dev.ctrl_transfer(0x40, 56, hid_id, 0, desc, timeout=3000)          # then the descriptor
dev.ctrl_transfer(0x40, 57, hid_id, 0, report, timeout=2000)        # then events
```

`wIndex` is stored as `report_desc_len`; `SET_HID_REPORT_DESC` accumulates bytes until
`offset == report_desc_len`, which is what triggers `acc_hid_init()` → `hid_add_device()`.
**Send exactly `len(desc)` bytes or the HID device is never created and every event is dropped silently.**

## Kernel side (AOSP `drivers/usb/gadget/function/f_accessory.c`)

```
REGISTER_HID -> acc_hid_new() (alloc buffer, offset=0, len=wIndex) -> new_hid_list
SET_HID_REPORT_DESC -> memcpy at offset; offset += actual
                       if offset == len: schedule_work(hid_work) -> acc_hid_init() -> hid_add_device()
SEND_HID_EVENT -> acc_complete_send_hid_event -> hid_report_raw_event(hid, HID_INPUT_REPORT, buf, len, 1)
```

Notes:
- `acc_register_hid()` uses **replace** semantics: registering an existing id moves the old
  entry to `dead_hid_list` and returns 0. So "register twice → expect EBUSY" is **not** a
  valid probe for whether init succeeded.
- `acc_hid_parse()` ignores `hid_parse_report()`'s return value, so a bad descriptor fails
  *silently* inside `hid_add_device`.
- `hid->dev.parent` **is** set (`acc_device.this_device`), vendor/product = `HID_ANY_ID`.
- If `hid_add_device` fails, `pr_err("can't add HID device")` goes to the **phone's** dmesg,
  which is unreachable without adb — i.e. nothing observable from the host.

## HID descriptors that registered successfully

Boot keyboard (63 B):
```
05 01 09 06 A1 01 05 07 19 E0 29 E7 15 00 25 01 75 01 95 08 81 02 95 01 75 08 81 01
95 05 75 01 05 08 19 01 29 05 91 02 95 01 75 03 91 01 95 06 75 08 15 00 25 65 05 07
19 00 29 65 81 00 C0
```
Report: 8 bytes `[modifier, reserved, k1..k6]`.

Absolute mouse (52 B, 16-bit 0..0x7FFF):
```
05 01 09 02 A1 01 09 01 A1 00 05 09 19 01 29 05 15 00 25 01 95 05 75 01 81 02 95 01
75 03 81 01 05 01 09 30 09 31 16 00 00 26 FF 7F 75 10 95 02 81 02 C0 C0
```
Report: 5 bytes `[buttons, x_hi, x_lo, y_hi, y_lo]`.

Relative mouse (67 B) and Consumer Control (23 B, POWER=0x0030) are in `aoa_hid.py`;
the Consumer one is useless for authorization probes (power key does not change USB state).

### HID keycodes used
`enter 0x28 · tab 0x2B · space 0x2C · esc 0x29 · backspace 0x2A · up 0x52 · down 0x51 · left 0x50 · right 0x4F`

## ADB wire protocol

Header: `struct.pack("<6I", cmd, arg0, arg1, data_length, data_check, magic)`
- `data_check = sum(payload) & 0xFFFFFFFF` (**not CRC32**)
- `magic = cmd ^ 0xFFFFFFFF`
- payload NUL-terminated
- `CNXN=0x4E584E43 AUTH=0x48545541 OKAY=0x59414B4F WRTE=0x45545257 CLSE=0x45534C43`
- A_AUTH token is 20 bytes at offset 24 of the payload

`data_length` is validated against MAX_PAYLOAD — sending `0xFFFFFFFF` or any oversized value
does nothing (no crash, no reset). Confirmed with a length ladder: 0x1000/0x8000/0xFFFF/
0x100000/0x100001/0x200000/0x7FFFFFFF/0xFFFFFFFF all behave identically.

## Authorization dialog (Huawei EMUI 10, 1080x2312 @ density 480)

`uiautomator dump` while the dialog is up:

| Node | resource-id | bounds | center |
|---|---|---|---|
| checkbox 始终允许 | `android:id/alwaysUse` | `[78,1133][1002,1277]` | (540, 1205) |
| 取消 | `android:id/button2` | `[84,1301][529,1421]` | (306, 1361) |
| 确定 | `android:id/button1` | `[555,1301][999,1421]` | (777, 1361) |

**The checkbox starts with `focused="true"`.** That is why the winning sequence is
`tab,enter`: TAB moves focus to 取消→确定 (D-pad focus order skips the checkbox because it
is already focused), ENTER activates. `space` toggles the checkbox instead of confirming.

## Failure modes and what they actually mean

| Symptom | Reality |
|---|---|
| `adb devices` → `authorizing` then back to `unauthorized` | adb server internal state during key exchange, **not** a click. Killing the server here aborts the flow. |
| device briefly `absent` right after injecting | adbd restarting because authorization succeeded — **wait 10-15s, do not kill-server** |
| every `ctrl_transfer` STALLs | wrong `REGISTER_HID` wIndex/wLength, or adb server holds the interface |
| writes fail only while adb server runs | pyusb and adb compete for the same endpoint → `adb kill-server` first |
| endpoint halt after a failed write | `dev.clear_halt(ep)` recovers it; power-cycling does **not** |

## Verifying that authorization is permanent

`/data/misc/adb/adb_keys` is `system:shell 640` — a `shell` uid cannot read it.
Verify behaviourally instead:

```bash
uhubctl -l 1-1 -p 3 -a off; sleep 10; uhubctl -l 1-1 -p 3 -a on; sleep 14
adb kill-server; adb devices        # expect: <serial>  device  (no dialog)
```

Key fingerprints: the dialog prints the **MD5** of the DER public key (`adbkey.pub`), so
compare with `base64 -d adbkey.pub | md5sum` before assuming a dialog belongs to you.

## Making wireless survive reboot

`adb tcpip 5555` does not persist. `setprop persist.adb.tcp.port 5555` is refused for
`shell` (SELinux). Android 10 has no Wi-Fi debugging pairing UI (that is 11+), so
`settings put global adb_wifi_enabled 1` is a no-op. The practical answer: USB authorization
persists, so after a reboot plug in USB (already `device`, no dialog) and re-run
`adb tcpip 5555`.
