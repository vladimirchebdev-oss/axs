#!/bin/sh
set -e
export DISPLAY=:99
echo "chrome: $(google-chrome --version 2>/dev/null || echo missing)  mode=headed-xvfb (no VNC)"

# docker restart оставляет lock/socket прошлого Xvfb — новый не стартует.
rm -f /tmp/.X99-lock /tmp/.X11-unix/X99
mkdir -p /tmp/.X11-unix
chmod 1777 /tmp/.X11-unix 2>/dev/null || true

Xvfb :99 -screen 0 1920x1080x24 -ac +extension RANDR -nolisten tcp &
i=0
while [ "$i" -lt 50 ]; do
  if [ -S /tmp/.X11-unix/X99 ]; then
    break
  fi
  i=$((i + 1))
  sleep 0.1
done
if [ ! -S /tmp/.X11-unix/X99 ]; then
  echo "Xvfb failed to start" >&2
  exit 1
fi

# Окно Chrome без WM на Xvfb часто без фокуса — Turnstile тогда крутится вечно.
openbox >/tmp/openbox.log 2>&1 &
sleep 0.3

exec python scripts/service.py
