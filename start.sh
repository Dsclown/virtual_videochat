#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
VENV="$ROOT/backend/.venv"

if [ ! -d "$VENV" ]; then
  python3 -m venv "$VENV"
  "$VENV/bin/pip" install -r "$ROOT/backend/requirements.txt"
  "$VENV/bin/pip" install -r "$ROOT/gateway/requirements.txt"
fi

if [ -n "${PLAYWRIGHT_BROWSERS_PATH:-}" ] && [[ "${PLAYWRIGHT_BROWSERS_PATH}" == *cursor-sandbox* ]]; then
  unset PLAYWRIGHT_BROWSERS_PATH
fi
if ! compgen -G "${HOME}/.cache/ms-playwright/chromium_headless_shell-*" > /dev/null; then
  echo "首次运行：下载 Playwright Chromium …"
  "$VENV/bin/playwright" install chromium
fi

if [ ! -f "$ROOT/backend/vtuber/grpc/v1/core_pb2.py" ]; then
  "$VENV/bin/python" "$ROOT/scripts/gen_grpc.py"
fi

CORE_PORT="${VVC_CORE_GRPC_PORT:-50051}"
ASSET_PORT="${VVC_CORE_ASSET_HTTP_PORT:-50052}"
HTTP_PORT="${VVC_HTTP_PORT:-8765}"
WEB_PORT="${VVC_WEB_PORT:-8780}"
GATEWAY_ORIGIN="${VVC_GATEWAY_ORIGIN:-http://127.0.0.1:${HTTP_PORT}}"

PIDS=()
cleanup() {
  for pid in "${PIDS[@]}"; do
    kill "$pid" 2>/dev/null || true
  done
}
trap cleanup EXIT INT TERM

# 后台进程：stdout/stderr 每行前加 [tag]，便于单终端区分
run_bg() {
  local tag=$1
  shift
  (
    "$@" 2>&1 | while IFS= read -r line || [ -n "${line:-}" ]; do
      printf '[%s] %s\n' "$tag" "$line"
    done
  ) &
  PIDS+=($!)
}

echo "启动 Core gRPC :${CORE_PORT} …"
run_bg core bash -c "
  cd \"$ROOT/backend\" &&
  export PYTHONPATH=\"$ROOT/backend\" &&
  export PYTHONUNBUFFERED=1 &&
  exec \"$VENV/bin/python\" core_main.py
"

sleep 2

echo "启动 Gateway :${HTTP_PORT} …"
run_bg gateway bash -c "
  cd \"$ROOT\" &&
  export PYTHONPATH=\"$ROOT/backend:$ROOT\" &&
  exec \"$VENV/bin/uvicorn\" gateway.main:app --host 0.0.0.0 --port \"$HTTP_PORT\" --no-access-log --log-level warning
"

echo "启动 Web 测试页 :${WEB_PORT} → Gateway ${GATEWAY_ORIGIN} …"
run_bg web bash -c "
  cd \"$ROOT\" &&
  export PYTHONPATH=\"$ROOT/backend:$ROOT\" &&
  export VVC_GATEWAY_ORIGIN=\"$GATEWAY_ORIGIN\" &&
  exec \"$VENV/bin/uvicorn\" web.main:app --host 0.0.0.0 --port \"$WEB_PORT\" --no-access-log --log-level warning
"

echo ""
echo "  Web 测试界面: http://127.0.0.1:${WEB_PORT}"
echo "  Gateway API:  ${GATEWAY_ORIGIN}"
echo "  Core gRPC:    127.0.0.1:${CORE_PORT}"
echo "  Core 资源 HTTP: 127.0.0.1:${ASSET_PORT}  (Live2D，Playwright)"
echo "  日志前缀: [core] [gateway] [web]"
echo ""

wait
