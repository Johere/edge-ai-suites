#!/usr/bin/env bash
# =============================================================================
# videostream-analytics 模块测试脚本
#
# 用法:
#   bash scripts/test-videostream-analytics.sh              # 运行全部测试
#   bash scripts/test-videostream-analytics.sh --unit-only  # 仅单元测试
#   bash scripts/test-videostream-analytics.sh --integration-only  # 仅集成测试
#   bash scripts/test-videostream-analytics.sh -v           # 详细输出
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
REPO_DIR="$(dirname "$PROJECT_DIR")"
PYTHON="${PROJECT_DIR}/.venv/bin/python"

if [[ ! -x "$PYTHON" ]]; then
    echo "Virtual env not found at ${PROJECT_DIR}/.venv"
    echo "Run: cd $PROJECT_DIR && python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'"
    exit 1
fi

# --- Configuration ---
MEDIAMTX_BIN="/home/lijie/.local/bin/mediamtx"
TEST_VIDEO="${REPO_DIR}/videos/phase2/child-care/composed/child_safety_demo.mp4"
DOCKER_IMAGE="agent-aismarthome-videostream-analytics:latest"
RTSP_PORT=8554
RTSP_PATH="live/child"
WEBHOOK_PORT=9999
ANALYTICS_PORT=8999

# --- Parse Arguments ---
RUN_UNIT=true
RUN_INTEGRATION=true
VERBOSE=""
PYTEST_ARGS=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --unit-only) RUN_INTEGRATION=false; shift ;;
        --integration-only) RUN_UNIT=false; shift ;;
        -v|--verbose) VERBOSE="-v"; PYTEST_ARGS="-v"; shift ;;
        *) echo "Unknown argument: $1"; exit 1 ;;
    esac
done

# --- Colors ---
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

info()  { echo -e "${BLUE}[INFO]${NC} $*"; }
ok()    { echo -e "${GREEN}[PASS]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
fail()  { echo -e "${RED}[FAIL]${NC} $*"; }

# --- Cleanup function ---
PIDS_TO_KILL=()
CONTAINER_NAME=""

cleanup() {
    info "Cleaning up..."
    # Stop Docker container
    if [[ -n "$CONTAINER_NAME" ]]; then
        docker stop "$CONTAINER_NAME" 2>/dev/null || true
        docker rm "$CONTAINER_NAME" 2>/dev/null || true
    fi
    # Kill background processes
    for pid in "${PIDS_TO_KILL[@]}"; do
        kill "$pid" 2>/dev/null || true
    done
    # Kill ffmpeg for our RTSP stream
    pkill -f "ffmpeg.*${RTSP_PATH}" 2>/dev/null || true
    # Stop MediaMTX if we started it
    if [[ "${MEDIAMTX_STARTED:-false}" == "true" ]]; then
        pkill -f "mediamtx" 2>/dev/null || true
    fi
    info "Cleanup complete."
}
trap cleanup EXIT

# =============================================================================
# UNIT TESTS
# =============================================================================
if $RUN_UNIT; then
    echo ""
    echo "═══════════════════════════════════════════════════════════════"
    echo "  UNIT TESTS"
    echo "═══════════════════════════════════════════════════════════════"
    echo ""

    cd "$PROJECT_DIR"

    # Check test video exists
    if [[ ! -f "$TEST_VIDEO" ]]; then
        fail "Test video not found: $TEST_VIDEO"
        exit 1
    fi
    info "Test video: $TEST_VIDEO"

    # Install dev dependencies if needed
    if ! $PYTHON -c "import pytest" 2>/dev/null; then
        info "Installing dev dependencies..."
        "${PROJECT_DIR}/.venv/bin/pip" install -e ".[dev]" --quiet --trusted-host pypi.org --trusted-host files.pythonhosted.org 2>/dev/null
    fi

    info "Running unit tests..."
    $PYTHON -m pytest tests/unit/ $PYTEST_ARGS --tb=short -q --timeout=60
    UNIT_EXIT=$?

    if [[ $UNIT_EXIT -eq 0 ]]; then
        ok "Unit tests PASSED"
    else
        fail "Unit tests FAILED (exit code: $UNIT_EXIT)"
        exit $UNIT_EXIT
    fi
fi

# =============================================================================
# INTEGRATION TESTS
# =============================================================================
if $RUN_INTEGRATION; then
    echo ""
    echo "═══════════════════════════════════════════════════════════════"
    echo "  INTEGRATION TESTS"
    echo "═══════════════════════════════════════════════════════════════"
    echo ""

    cd "$PROJECT_DIR"

    # Check prerequisites
    if [[ ! -f "$TEST_VIDEO" ]]; then
        fail "Test video not found: $TEST_VIDEO"
        exit 1
    fi
    if ! docker image inspect "$DOCKER_IMAGE" &>/dev/null; then
        fail "Docker image not found: $DOCKER_IMAGE"
        exit 1
    fi
    if [[ ! -x "$MEDIAMTX_BIN" ]]; then
        fail "MediaMTX not found: $MEDIAMTX_BIN"
        exit 1
    fi

    # --- Step 1: Start MediaMTX ---
    if lsof -i:$RTSP_PORT -t &>/dev/null; then
        info "MediaMTX already running on port $RTSP_PORT"
        MEDIAMTX_STARTED=false
    else
        info "Starting MediaMTX..."
        "$MEDIAMTX_BIN" &>/dev/null &
        PIDS_TO_KILL+=($!)
        MEDIAMTX_STARTED=true
        sleep 2
        if ! lsof -i:$RTSP_PORT -t &>/dev/null; then
            fail "MediaMTX failed to start on port $RTSP_PORT"
            exit 1
        fi
        ok "MediaMTX started on :$RTSP_PORT"
    fi

    # --- Step 2: Start ffmpeg RTSP push ---
    info "Starting ffmpeg RTSP push: $TEST_VIDEO → rtsp://localhost:$RTSP_PORT/$RTSP_PATH (seek to 40s for motion)"
    ffmpeg -re -stream_loop -1 -ss 40 -i "$TEST_VIDEO" \
        -c copy -f rtsp \
        "rtsp://localhost:$RTSP_PORT/$RTSP_PATH" \
        </dev/null &>/dev/null &
    PIDS_TO_KILL+=($!)
    sleep 3

    # Verify RTSP stream is available
    if ffprobe -v quiet -i "rtsp://localhost:$RTSP_PORT/$RTSP_PATH" -show_entries stream=codec_name 2>/dev/null | grep -q "h264"; then
        ok "RTSP stream available at rtsp://localhost:$RTSP_PORT/$RTSP_PATH"
    else
        warn "RTSP stream verification failed (may still work)"
    fi

    # --- Step 3: Start mock webhook server ---
    info "Starting mock webhook server on :$WEBHOOK_PORT..."
    $PYTHON -m uvicorn tests.integration.mock_webhook_server:app \
        --host 0.0.0.0 --port $WEBHOOK_PORT --log-level warning &
    PIDS_TO_KILL+=($!)
    sleep 2

    if curl -sf "http://localhost:$WEBHOOK_PORT/health" >/dev/null; then
        ok "Mock webhook server running on :$WEBHOOK_PORT"
    else
        fail "Mock webhook server failed to start"
        exit 1
    fi

    # --- Step 4: Start Docker container ---
    CONTAINER_NAME="videostream-analytics-test-$$"
    info "Starting Docker container: $DOCKER_IMAGE (--network host)"

    docker run -d --rm \
        --name "$CONTAINER_NAME" \
        --network host \
        -e WEBHOOK_URL="http://localhost:$WEBHOOK_PORT/events" \
        -e no_proxy="localhost,127.0.0.1" \
        -e http_proxy="" \
        -e https_proxy="" \
        -v "$HOME/models:/models:ro" \
        -v /tmp/smartbuilding-clips:/root/.smartbuilding/data \
        "$DOCKER_IMAGE" \
        python -m src.main --host 0.0.0.0 --port $ANALYTICS_PORT
    sleep 3

    # Verify container is healthy
    RETRIES=10
    while [[ $RETRIES -gt 0 ]]; do
        if curl -sf "http://localhost:$ANALYTICS_PORT/health" >/dev/null; then
            break
        fi
        RETRIES=$((RETRIES - 1))
        sleep 1
    done

    if curl -sf "http://localhost:$ANALYTICS_PORT/health" >/dev/null; then
        ok "Docker container healthy on :$ANALYTICS_PORT"
    else
        fail "Docker container failed to start or become healthy"
        docker logs "$CONTAINER_NAME" 2>&1 | tail -20
        exit 1
    fi

    # --- Step 5: Run integration tests ---
    info "Running integration tests..."
    $PYTHON -m pytest tests/integration/ $PYTEST_ARGS --tb=short -q -m integration --timeout=360
    INTEG_EXIT=$?

    if [[ $INTEG_EXIT -eq 0 ]]; then
        ok "Integration tests PASSED"
    else
        fail "Integration tests FAILED (exit code: $INTEG_EXIT)"
        info "Container logs (last 30 lines):"
        docker logs "$CONTAINER_NAME" 2>&1 | tail -30
        exit $INTEG_EXIT
    fi
fi

# =============================================================================
# SUMMARY
# =============================================================================
echo ""
echo "═══════════════════════════════════════════════════════════════"
echo -e "  ${GREEN}ALL TESTS PASSED${NC}"
echo "═══════════════════════════════════════════════════════════════"
echo ""
