#!/bin/bash
# Retry AOA HID key injection until `adb devices` reports "device".
#
#   ./autohit.sh [serial] [adb-path]
#
# Env:
#   COMBOS   space-separated list of key combos (default below)
#   MAX_RUNS 0 = forever
#   SLEEP    seconds between rounds (default 4)
#
# IMPORTANT: every round kills adb server first (frees the USB interface for
# pyusb), then injects, then queries. Do NOT interrupt once a round starts —
# the adbd restart after a successful authorization takes 5-15s.

set -u
SERIAL="${1:-}"
ADB="${2:-${ADB:-adb}}"
HERE="$(cd "$(dirname "$0")" && pwd)"
PY="${PYTHON:-python3}"
LOG="${LOG:-/tmp/aoa_autohit.log}"
MAX_RUNS="${MAX_RUNS:-0}"
SLEEP="${SLEEP:-4}"

# Order matters: tab,enter hits when focus starts on the "always allow" checkbox.
COMBOS="${COMBOS:-tab,enter tab,tab,enter tab,tab,tab,enter down,enter down,down,enter space,enter tab,space,enter}"

if [ -z "$SERIAL" ]; then
  SERIAL=$($ADB devices 2>/dev/null | awk '$2=="unauthorized"{print $1; exit}')
fi
[ -z "$SERIAL" ] && { echo "[-] no unauthorized device; pass serial as \$1"; exit 1; }

echo "=== start $(date '+%F %T') serial=$SERIAL ===" | tee -a "$LOG"
i=0
while :; do
  st=$($ADB devices 2>/dev/null | awk -v s="$SERIAL" '$1==s{print $2}')
  if [ "$st" = "device" ]; then
    echo "[+] $(date +%T) DEVICE — authorized" | tee -a "$LOG"
    $ADB -s "$SERIAL" shell true 2>/dev/null && echo "[+] shell OK" | tee -a "$LOG"
    exit 0
  fi

  $ADB kill-server >/dev/null 2>&1
  sleep 0.4
  combo=$(echo "$COMBOS" | cut -d' ' -f$(( i % $(echo "$COMBOS" | wc -w) + 1 )))
  $PY "$HERE/aoa_hid.py" --keys "$combo" >/dev/null 2>&1
  st=$($ADB devices 2>/dev/null | awk -v s="$SERIAL" '$1==s{print $2}')
  echo "$(date +%T) combo=$combo -> ${st:-absent}" | tee -a "$LOG"

  i=$((i+1))
  if [ "$MAX_RUNS" -gt 0 ] && [ "$i" -ge "$MAX_RUNS" ]; then
    echo "[-] max runs reached" | tee -a "$LOG"
    exit 2
  fi
  sleep "$SLEEP"
done
