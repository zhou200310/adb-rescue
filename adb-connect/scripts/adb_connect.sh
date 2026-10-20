#!/bin/bash
# adb_connect.sh — get an ADB connection up, over USB or Wi-Fi.
#
#   ./adb_connect.sh status                 # what does adb see right now
#   ./adb_connect.sh usb                    # enumerate USB + fix node perms
#   ./adb_connect.sh perms                  # chmod /dev/bus/usb nodes (needs privilege)
#   ./adb_connect.sh wifi <ip> [port]       # adb tcpip + connect + verify
#   ./adb_connect.sh scan [subnet] [port]   # find hosts with adb port open, connect all
#   ./adb_connect.sh reset                  # kill/start server, drop and retry links
#
# Env: ADB (binary), DOCKER_PRIV (container for privileged chmod, default aoatool)

set -u
ADB="${ADB:-}"
if [ -z "$ADB" ]; then
  if command -v adb >/dev/null 2>&1; then ADB=$(command -v adb)
  elif [ -x /tmp/pt/platform-tools/adb ]; then ADB=/tmp/pt/platform-tools/adb
  else echo "[-] adb not found; set ADB=/path/to/adb"; exit 1; fi
fi
DOCKER_PRIV="${DOCKER_PRIV:-aoatool}"
PORT_DEFAULT=5555

say() { printf '%s\n' "$*"; }

do_perms() {
  if [ -d /dev/bus/usb ]; then
    if [ -n "$DOCKER_PRIV" ] && docker ps --format '{{.Names}}' 2>/dev/null | grep -qx "$DOCKER_PRIV"; then
      docker exec "$DOCKER_PRIV" bash -c 'for p in /dev/bus/usb/*/*; do chmod 777 "$p" 2>/dev/null; done' \
        && say "[+] node perms fixed via container $DOCKER_PRIV" && return 0
    fi
    if for p in /dev/bus/usb/*/*; do chmod 777 "$p" 2>/dev/null || exit 1; done; then
      say "[+] node perms fixed directly"; return 0
    fi
    say "[!] cannot chmod (need root). Run in a privileged container:"
    say "    docker exec $DOCKER_PRIV bash -c 'chmod 777 /dev/bus/usb/*/*'"
    return 1
  fi
  say "[!] /dev/bus/usb not present — is USB passed into this namespace?"
  return 1
}

do_status() {
  say "── lsusb (android-ish) ──"
  lsusb 2>/dev/null | grep -iE '12d1|18d1|2717|04e8|2a70|05c6|22d9' || say "  (none)"
  say "── adb devices ──"
  "$ADB" devices -l 2>&1 | sed '/^$/d'
}

do_usb() {
  do_perms
  "$ADB" start-server >/dev/null 2>&1
  say "── usb enumeration ──"
  lsusb 2>/dev/null | grep -iE '12d1|18d1|2717|04e8|2a70|05c6|22d9' || say "  no android device on the bus"
  do_status
}

do_wifi() {
  local ip="${1:-}" port="${2:-$PORT_DEFAULT}"
  [ -z "$ip" ] && { say "[-] usage: wifi <ip> [port]"; exit 1; }
  local serial="$ip:$port"
  # if USB is attached, switch adbd into tcp mode first
  local usb_serial
  usb_serial=$("$ADB" devices 2>/dev/null | awk 'NR>1 && $2=="device" && $1 !~ /:/ {print $1; exit}')
  if [ -n "$usb_serial" ]; then
    say "[=] usb device $usb_serial present, switching adbd to tcp"
    "$ADB" -s "$usb_serial" tcpip "$port" 2>&1 | sed 's/^/    /'
    sleep 3
  fi
  "$ADB" connect "$serial" 2>&1 | sed 's/^/    /'
  sleep 2
  local st
  st=$("$ADB" devices | awk -v s="$serial" '$1==s{print $2}')
  if [ "$st" = "device" ]; then
    say "[+] $serial device"
    "$ADB" -s "$serial" shell true 2>/dev/null && say "[+] shell OK"
    "$ADB" -s "$serial" shell 'getprop ro.product.model; getprop ro.build.version.release' 2>/dev/null | sed 's/^/    /'
    return 0
  fi
  say "[!] $serial -> ${st:-absent}"
  return 2
}

do_scan() {
  local subnet="${1:-}" port="${2:-$PORT_DEFAULT}"
  if [ -z "$subnet" ]; then
    subnet=$(ip -4 addr 2>/dev/null | awk '/inet /{print $2}' | grep -v '^127\.' | head -1 | cut -d/ -f1 | cut -d. -f1-3)
    [ -z "$subnet" ] && { say "[-] cannot detect subnet; pass it explicitly"; exit 1; }
  fi
  say "[=] scanning $subnet.0/24 port $port"
  seq 1 254 | xargs -P 96 -I{} sh -c "timeout 0.4 bash -c 'echo > /dev/tcp/$subnet.{}/$port' 2>/dev/null && echo $subnet.{}" \
    | sort -t. -k4 -n > /tmp/adb_scan.$$
  if [ ! -s /tmp/adb_scan.$$ ]; then say "[-] no host with :$port open"; rm -f /tmp/adb_scan.$$; return 1; fi
  while read -r ip; do
    say "[+] found $ip:$port"
    "$ADB" connect "$ip:$port" 2>&1 | sed 's/^/    /'
  done < /tmp/adb_scan.$$
  rm -f /tmp/adb_scan.$$
  sleep 2
  do_status
}

do_reset() {
  say "[=] restarting adb server"
  "$ADB" kill-server >/dev/null 2>&1
  sleep 1
  "$ADB" start-server >/dev/null 2>&1
  sleep 1
  "$ADB" devices -l 2>&1 | sed '/^$/d'
}

case "${1:-status}" in
  status) do_status ;;
  usb)    do_usb ;;
  perms)  do_perms ;;
  wifi)   shift; do_wifi "$@" ;;
  scan)   shift; do_scan "$@" ;;
  reset)  do_reset ;;
  *) say "usage: $0 {status|usb|perms|wifi <ip> [port]|scan [subnet] [port]|reset}"; exit 1 ;;
esac
