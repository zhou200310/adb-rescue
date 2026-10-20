# ADB connection troubleshooting

## Symptom → cause → action

| Symptom | Most likely cause | Action |
|---|---|---|
| `adb devices` empty, `lsusb` shows nothing | cable / hub / port off | reseat, try another port, `uhubctl -a on` |
| `lsusb` shows the phone but adb is empty | wrong gadget mode (charge-only / MTP) or adbd not running | change USB mode on device, `adb kill-server; adb start-server` |
| `no permissions (user X is not in the plugdev group)` | `/dev/bus/usb/BBB/DDD` is `root:root 0644` | chmod in a privileged context, re-run **after every re-enumeration** |
| `error: device unauthorized` | RSA key not in `/data/misc/adb/adb_keys` | press the dialog (see `adb-aoa-hid`) |
| `authorizing` never becomes `device` | adb server killed mid-handshake, or the dialog was dismissed | leave the server alone for 15s; retry the dialog |
| `error: device offline` | handshake stalled, or the peer on that port is not adbd | `adb disconnect <serial>` then reconnect; verify it is a real device first |
| `more than one device/emulator` | USB and Wi-Fi both attached | add `-s <serial>` (Wi-Fi serial is `ip:port`) |
| `adb tcpip 5555` says ok, `connect` says refused | adbd restarted before the port opened | wait 3-5s and retry; verify Wi-Fi is up on the device |
| Works, then dies minutes later | DHCP lease / device slept / Wi-Fi power save | run `adb_keeper.sh`; set a DHCP reservation |
| `adb shell` works but `pull` is slow | USB 1.1 hub or a busy HID path | check `lsusb -t`, move off the hub |

## Recognizing a device family from `lsusb`

| VID | Vendor | Notes |
|---|---|---|
| `12d1` | Huawei | `107e` = normal composite (MTP+ADB); `107d`/`107e` variants by firmware |
| `18d1` | Google | `2d01` = AOA accessory + ADB; `4ee7` = normal ADB; `4ee1` = MTP |
| `2717` | Xiaomi | needs "USB debugging (Security settings)" for `input`/`install` |
| `04e8` | Samsung | `6860` = MTP+ADB, `685d` = ADB only |
| `2a70` | OnePlus | `9011` = composite |
| `05c6` | Qualcomm | `9008` = EDL (not adb) |

## Finding a phone's IP without touching it

```bash
ip neigh | grep -i '<mac-prefix>'          # ARP after a ping sweep
bash scripts/adb_connect.sh scan 192.168.10  # probes :5555 directly
adb -s <usb-serial> shell 'ip -4 addr show wlan0'
```

`scan` opens a TCP connection to `:5555` with a 0.4s timeout across /24 in parallel — much
faster and more reliable than ping on networks that drop ICMP.

## Wireless facts worth remembering

- `adb tcpip <port>` is **not** persistent; a reboot returns adbd to USB-only.
- `persist.adb.tcp.port` cannot be set from `shell` (SELinux denies).
- `adb pair` (wireless debugging with a code) requires Android 11+.
- Any host on the LAN that reaches `:5555` will trigger the authorization dialog, and if a
  human ticks "always allow", **that host is permanently trusted**. If a dialog appears with a
  fingerprint you do not recognize, confirm it is the owner's machine before accepting —
  compare against `base64 -d adbkey.pub | md5sum`.
- Once authorized, the key survives reboots, which is why USB bring-up is the reliable
  bootstrap for wireless.

## Environment traps

- `/tmp` is wiped on this host — keep scripts and helper files in the workspace.
- The adb server owns the USB interface: `adb kill-server` before pyusb/libusb work, and stop
  any keeper loop first.
- Node permissions reset on every re-enumeration; a devnum change also means any open handle
  or `transport_id` is stale.
