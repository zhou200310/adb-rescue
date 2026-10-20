---
name: adb-connect
description: Establish, repair and keep alive an ADB connection to a physical Android device over USB or Wi-Fi, and decode every `adb devices` state (device / unauthorized / authorizing / offline / no permissions / absent). Use when adb cannot see a phone, when nodes under /dev/bus/usb report "no permissions (user is not in plugdev group)", when USB enumeration is flaky, when wireless adb on port 5555 must be enabled or restored after a reboot, when several devices are attached and commands need `-s`, or when a long-running link needs a reconnect keeper.
---

# ADB connection: bring-up, repair, keep-alive

Two transports, one rule: **get `device`, then keep it.**

## 1. Locate a working adb binary

```bash
command -v adb || ls /tmp/pt/platform-tools/adb
adb version
```

Prefer a recent platform-tools. Distro packages can be years old (Debian ships 1.0.41 / 29.0.6),
which lacks newer `adb pair`, `mdns` and some `tcpip` behaviours.
**Never store scripts in `/tmp`** — it gets wiped without warning. Keep them in the workspace.

## 2. See what is actually there

```bash
bash scripts/adb_connect.sh status
bash scripts/adb_connect.sh usb     # also fixes /dev/bus/usb perms first
```

Android vendor IDs worth grepping in `lsusb`: `12d1` Huawei, `18d1` Google/accessory,
`2717` Xiaomi, `04e8` Samsung, `2a70` OnePlus, `05c6` Qualcomm, `22d9` OPPO.
A Huawei body that changes `12d1:xxxx` → `18d1:2d01` has been switched into AOA accessory mode.

## 3. Fix node permissions — after *every* re-enumeration

`no permissions (user <u> is not in the plugdev group)` is a host permission problem, not a
device problem. The devnum changes each time the device re-enumerates, and the new node comes
back as `root:root 0644` again.

```bash
bash scripts/adb_connect.sh perms
# equivalent, needs a privileged container:
docker exec <priv-container> bash -c 'for p in /dev/bus/usb/*/*; do chmod 777 "$p"; done'
```

## 4. Bring up the link

**USB:** plug in, run `adb_connect.sh usb`, confirm `device`.
**Wi-Fi:**

```bash
bash scripts/adb_connect.sh wifi <phone-ip> 5555   # runs adb tcpip when USB is attached, then connects
bash scripts/adb_connect.sh scan 192.168.10       # find hosts with :5555 open and connect them
```

`adb tcpip 5555` restarts adbd: the USB link drops for a few seconds. That is expected —
reconnect, do not "fix" it.

**Several devices:** always pass a serial. `adb -s <serial>` where serial is either the USB
serial or `ip:port`. `adb devices -l` shows `transport_id` when you need to disambiguate.

## 5. Keep it alive

```bash
LOG=/tmp/adb_keeper.log nohup bash scripts/adb_keeper.sh 192.168.1.50:5555 5 &
```

It reconnects on drop and logs only state transitions. Kill with `pkill -f adb_keeper.sh`.

## 6. Recovering wireless after a reboot

`adb tcpip` state does not persist:
- `setprop persist.adb.tcp.port 5555` → refused for `shell` (SELinux).
- Android 10 and older have no wireless-debugging pairing at all (`adb pair` is 11+).
- `settings put global adb_wifi_enabled 1` is a no-op below 11.

What does persist is the RSA authorization in `/data/misc/adb/adb_keys`. So the recovery path is:
plug in USB → it is already `device` → `adb tcpip 5555` → connect over Wi-Fi → unplug.
If the phone is **still `unauthorized`** after USB, authorization was never granted — use the
`adb-aoa-hid` skill to press the dialog.

## 7. States and what they mean

| State | Meaning | Fix |
|---|---|---|
| `device` | authorized and usable | — |
| `unauthorized` | RSA key not accepted yet; dialog pending | `adb-aoa-hid` skill |
| `authorizing` | key exchange mid-flight; transient | wait 15s, **never** kill-server here |
| `offline` | port answers but it is not a healthy adbd, or handshake stalled | `adb disconnect`, reconnect; if it persists it is probably not adbd |
| `no permissions (...)` | `/dev/bus/usb` node perms | `adb_connect.sh perms` |
| `absent` | device not on the bus | check cable/hub, `adb kill-server` |
| `more than one device` | two transports to the same phone | use `-s <serial>` |

## 8. Conflicts to remember

- An adb server **holds the USB interface**. Before any raw `pyusb`/libusb work:
  `adb kill-server` and stop the keeper, or writes fail/STALL.
- Endpoint halts from a failed raw transfer clear with `dev.clear_halt(ep)`, not a power cycle.
- A hub power cycle (`uhubctl -l <loc> -p <port> -a off/on`) is the cleanest way to simulate
  unplugging; allow 10-15s for re-enumeration.
- `adb connect` to a random port that answers but returns `offline` is **not** evidence of adbd —
  IoT and proxy services also hold sockets.

Detailed symptom→cause table: [references/troubleshooting.md](references/troubleshooting.md).
