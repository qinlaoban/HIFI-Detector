#!/bin/bash
# 开发环境启动脚本
#   ./dev.sh             浏览器模式：后端(8099) + Vite dev server(5173)
#   ./dev.sh --desktop   桌面模式：后端(8099) + Tauri 窗口（不需要 Vite）
#   ./dev.sh [port]      自定义后端端口
# Ctrl+C 同时退出全部进程

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON="$SCRIPT_DIR/.venv/bin/python"
PORT=8099
MODE="browser"

for arg in "$@"; do
    case "$arg" in
        --desktop|-d) MODE="desktop" ;;
        *) PORT="$arg" ;;
    esac
done

# 清理上次残留的进程（仅杀 LISTEN 的，避免误杀浏览器的普通连接）
echo "=== 清理残留进程 ==="
for p in $(lsof -ti:"$PORT" -sTCP:LISTEN 2>/dev/null); do kill "$p" 2>/dev/null; done
for p in $(lsof -ti:5173 -sTCP:LISTEN 2>/dev/null); do kill "$p" 2>/dev/null; done
sleep 1

echo "=== 启动后端 (127.0.0.1:$PORT) ==="
"$PYTHON" -m hifi_detector.cli web --no-open --port "$PORT" &
BACK_PID=$!

FRONT_PID=""
cleanup() {
    echo ""
    echo "=== 正在退出 ==="
    kill "$BACK_PID" 2>/dev/null
    [ -n "$FRONT_PID" ] && kill "$FRONT_PID" 2>/dev/null
}
trap cleanup EXIT INT TERM

if [ "$MODE" = "desktop" ]; then
    echo "=== 启动 Tauri 桌面窗口 ==="
    cd "$SCRIPT_DIR/tauri"
    npx tauri dev &
    FRONT_PID=$!
else
    echo "=== 启动前端 (http://localhost:5173) ==="
    cd "$SCRIPT_DIR/web"
    API_PROXY="http://127.0.0.1:$PORT" npm run dev &
    FRONT_PID=$!
fi

while true; do
    if ! kill -0 "$BACK_PID" 2>/dev/null; then
        echo "后端进程已退出"
        break
    fi
    if [ -n "$FRONT_PID" ] && ! kill -0 "$FRONT_PID" 2>/dev/null; then
        echo "前端进程已退出"
        break
    fi
    sleep 1
done
