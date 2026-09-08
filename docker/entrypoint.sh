#!/bin/sh
set -e
export DISPLAY=:99
echo "chrome: $(google-chrome --version 2>/dev/null || echo missing)"

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

# Без пароля: x11vnc слушает только 127.0.0.1, наружу идёт websockify :6080.
rm -f /tmp/x11vnc.log /tmp/novnc.log
x11vnc -display :99 -forever -shared -nopw -rfbport 5900 -listen 127.0.0.1 \
  -xkb -noxdamage >/tmp/x11vnc.log 2>&1 &
i=0
while [ "$i" -lt 50 ]; do
  if python -c "import socket; socket.create_connection(('127.0.0.1', 5900), 0.2).close()" \
    >/dev/null 2>&1; then
    break
  fi
  i=$((i + 1))
  sleep 0.1
done
if ! python -c "import socket; socket.create_connection(('127.0.0.1', 5900), 0.5).close()" \
  >/dev/null 2>&1; then
  echo "x11vnc failed to listen on 5900" >&2
  cat /tmp/x11vnc.log >&2 || true
  exit 1
fi

websockify --web /usr/share/novnc 6080 127.0.0.1:5900 >/tmp/novnc.log 2>&1 &
exec python scripts/service.py
