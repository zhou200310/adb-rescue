#!/bin/bash
# adb_keeper.sh — keep a Wi-Fi ADB link alive.
#
#   ./adb_keeper.sh <ip>[:port] [interval_seconds]
#
# Reconnects whenever the device drops out of `adb devices` as "device".
# Logs state transitions only (not every poll), so it is safe to leave running.
#
#   LOG=/tmp/adb_keeper.log nohup ./adb_keeper.sh 192.168.1.50:5555 5 &
#
# Stop with: pkill -f adb_keeper.sh

set -u
ADB="${ADB:-$(command -v adb || echo /tmp/pt/platform-tools/adb)}"
TARGET="${1:?usage: adb_keeper.sh <ip>[:port] [interval]}"
case "$TARGET" in *:*) ;; *) TARGET="$TARGET:5555" ;; esac
INTERVAL="${2:-5}"
LOG="${LOG:-/tmp/adb_keeper.log}"

prev=""
log() { echo "$(date '+%F %T') $*" >>"$LOG"; }

log "=== keeper start target=$TARGET interval=${INTERVAL}s ==="
while :; do
  st=$("$ADB" devices 2>/dev/null | awk -v t="$TARGET" '$1==t{print $2}')
  if [ "$st" != "device" ]; then
    "$ADB" connect "$TARGET" >/dev/null 2>&1
    st2=$("$ADB" devices 2>/dev/null | awk -v t="$TARGET" '$1==t{print $2}')
    if [ "$st2" = "device" ]; then
      log "reconnected  (was: ${st:-absent})"
      prev="device"
    elif [ "${prev:-x}" != "${st2:-absent}" ]; then
      log "still down   (${st2:-absent})"
      prev="${st2:-absent}"
    fi
  elif [ "$prev" != "device" ]; then
    log "connected"
    prev="device"
  fi
  sleep "$INTERVAL"
done
