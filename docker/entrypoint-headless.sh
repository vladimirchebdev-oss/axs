#!/bin/sh
set -e
echo "chrome: $(google-chrome --version 2>/dev/null || echo missing)  mode=headless"
exec python scripts/service.py
