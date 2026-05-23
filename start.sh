#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/backend"

if [ ! -d ".venv" ]; then
  python3 -m venv .venv
  .venv/bin/pip install -r requirements.txt
fi

# Playwright 浏览器装到 ~/.cache/ms-playwright（勿依赖 IDE 沙箱里的 PLAYWRIGHT_BROWSERS_PATH）
if [ -n "${PLAYWRIGHT_BROWSERS_PATH:-}" ] && [[ "${PLAYWRIGHT_BROWSERS_PATH}" == *cursor-sandbox* ]]; then
  unset PLAYWRIGHT_BROWSERS_PATH
fi
if ! compgen -G "${HOME}/.cache/ms-playwright/chromium_headless_shell-*" > /dev/null; then
  echo "首次运行：下载 Playwright Chromium（约 100MB）…"
  .venv/bin/playwright install chromium
fi

exec .venv/bin/uvicorn main:app --host 0.0.0.0 --port 8765 --reload
