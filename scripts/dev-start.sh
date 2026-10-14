#!/usr/bin/env bash
# ==============================================================================
# Electrical AI Platform - One-Click Local Development Startup Script
#
# Requirements:
#   - Python 3.12+ (or uv)
#   - Node.js 20+ & npm
#
# Usage:
#   ./scripts/dev-start.sh
# ==============================================================================

set -euo pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo -e "${CYAN}==============================================================================${NC}"
echo -e "${CYAN}  Electrical AI Platform (전기공사 AI 플랫폼) - 로컬 시연 환경 시작${NC}"
echo -e "${CYAN}==============================================================================${NC}"

# 1. Dependency Checks
echo -e "\n${BLUE}[1/4] 실행 환경 및 필수 도구 점검...${NC}"

# Check Python version (>= 3.12)
PYTHON_BIN=""
if command -v python3 >/dev/null 2>&1; then
    PY_VER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
    PY_MAJOR=$(echo "$PY_VER" | cut -d. -f1)
    PY_MINOR=$(echo "$PY_VER" | cut -d. -f2)
    if [ "$PY_MAJOR" -ge 3 ] && [ "$PY_MINOR" -ge 12 ]; then
        PYTHON_BIN="python3"
    fi
fi

if [ -z "$PYTHON_BIN" ] && [ -f "$ROOT_DIR/.venv/bin/python" ]; then
    VENV_VER=$("$ROOT_DIR/.venv/bin/python" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
    VENV_MAJOR=$(echo "$VENV_VER" | cut -d. -f1)
    VENV_MINOR=$(echo "$VENV_VER" | cut -d. -f2)
    if [ "$VENV_MAJOR" -ge 3 ] && [ "$VENV_MINOR" -ge 12 ]; then
        PYTHON_BIN="$ROOT_DIR/.venv/bin/python"
    fi
fi

if [ -z "$PYTHON_BIN" ]; then
    echo -e "${RED}[오류] Python 3.12 이상이 설치되어 있지 않습니다.${NC}"
    echo -e "설치 안내: https://www.python.org/downloads/ 또는 'brew install python@3.12'"
    exit 1
fi
echo -e "  ${GREEN}✓${NC} Python: $($PYTHON_BIN --version) ($PYTHON_BIN)"

# Check Node.js version (>= 20)
if ! command -v node >/dev/null 2>&1; then
    echo -e "${RED}[오류] Node.js가 설치되어 있지 않습니다.${NC}"
    echo -e "설치 안내: https://nodejs.org/ (Node 20+ LTS 권장)"
    exit 1
fi

NODE_VER=$(node -v | tr -d 'v')
NODE_MAJOR=$(echo "$NODE_VER" | cut -d. -f1)
if [ "$NODE_MAJOR" -lt 20 ]; then
    echo -e "${RED}[오류] Node.js 20 이상이 필요합니다 (현재: v${NODE_VER}).${NC}"
    exit 1
fi
echo -e "  ${GREEN}✓${NC} Node.js: v${NODE_VER}"

# Check npm
if ! command -v npm >/dev/null 2>&1; then
    echo -e "${RED}[오류] npm이 설치되어 있지 않습니다.${NC}"
    exit 1
fi
echo -e "  ${GREEN}✓${NC} npm: $(npm -v)"

# Check virtual environment & dependencies
if [ ! -d "$ROOT_DIR/.venv" ]; then
    echo -e "${YELLOW}[안내] Python 가상환경(.venv)이 없습니다. 가상환경을 생성합니다...${NC}"
    if command -v uv >/dev/null 2>&1; then
        uv sync
    else
        $PYTHON_BIN -m venv "$ROOT_DIR/.venv"
        "$ROOT_DIR/.venv/bin/pip" install -e "packages/cad_engine" -e "apps/api"
    fi
fi

# Check frontend node_modules
if [ ! -d "$ROOT_DIR/apps/web/node_modules" ]; then
    echo -e "${YELLOW}[안내] 프론트엔드 node_modules가 없습니다. 의존성을 설치합니다...${NC}"
    (cd "$ROOT_DIR/apps/web" && npm install)
fi

# 2. Port Conflict Checks
echo -e "\n${BLUE}[2/4] 포트 충돌 확인 (API: 8000, Web: 3000)...${NC}"

API_PID=$(lsof -ti :8000 || true)
WEB_PID=$(lsof -ti :3000 || true)

if [ -n "$API_PID" ]; then
    echo -e "${YELLOW}  포트 8000이 이미 사용 중입니다 (PID: $API_PID).${NC}"
    echo -e "  기존 프로세스를 계속 재사용하거나, 필요 시 './scripts/dev-stop.sh'로 종료 후 다시 실행하세요."
fi

if [ -n "$WEB_PID" ]; then
    echo -e "${YELLOW}  포트 3000이 이미 사용 중입니다 (PID: $WEB_PID).${NC}"
    echo -e "  기존 프로세스를 계속 재사용하거나, 필요 시 './scripts/dev-stop.sh'로 종료 후 다시 실행하세요."
fi

# 3. Starting Servers
echo -e "\n${BLUE}[3/4] 백엔드 API 및 프론트엔드 웹 앱 기동...${NC}"

PIDS=()

cleanup() {
    echo -e "\n${YELLOW}[종료] 서버 프로세스를 정리하는 중...${NC}"
    for pid in "${PIDS[@]}"; do
        if kill -0 "$pid" 2>/dev/null; then
            kill "$pid" 2>/dev/null || true
        fi
    done
    wait 2>/dev/null || true
    echo -e "${GREEN}[완료] 모든 로컬 서버가 안전하게 종료되었습니다.${NC}"
    exit 0
}

trap cleanup SIGINT SIGTERM EXIT

# Start API if not running
if [ -z "$API_PID" ]; then
    echo -e "  -> FastAPI 백엔드 시작 (포트 8000)..."
    PYTHONPATH="apps/api/src:packages/cad_engine/src" \
    "$ROOT_DIR/.venv/bin/uvicorn" eai_api.app:app --host 127.0.0.1 --port 8000 > /tmp/eai_api.log 2>&1 &
    API_PID=$!
    PIDS+=("$API_PID")
else
    echo -e "  -> 기존 실행 중인 백엔드(PID: $API_PID)에 연결합니다."
fi

# Start Next.js if not running
if [ -z "$WEB_PID" ]; then
    echo -e "  -> Next.js 프론트엔드 시작 (포트 3000)..."
    (cd "$ROOT_DIR/apps/web" && npm run dev -- -p 3000) > /tmp/eai_web.log 2>&1 &
    WEB_PID=$!
    PIDS+=("$WEB_PID")
else
    echo -e "  -> 기존 실행 중인 프론트엔드(PID: $WEB_PID)에 연결합니다."
fi

# 4. Wait for Health Readiness
echo -e "\n${BLUE}[4/4] 서비스 준비 완료 대기 중...${NC}"

# Check API health
API_READY=false
for i in {1..20}; do
    if curl -s "http://127.0.0.1:8000/api/health" | grep -q "ok"; then
        API_READY=true
        break
    fi
    sleep 0.5
done

if [ "$API_READY" = false ]; then
    echo -e "${RED}[오류] API 백엔드 시작 실패. 로그 확인: /tmp/eai_api.log${NC}"
    exit 1
fi
echo -e "  ${GREEN}✓${NC} API 서버 준비 완료: http://127.0.0.1:8000"

# Check Web health
WEB_READY=false
for i in {1..30}; do
    if curl -s -I "http://localhost:3000" | grep -q "200 OK"; then
        WEB_READY=true
        break
    fi
    sleep 0.5
done

if [ "$WEB_READY" = false ]; then
    echo -e "${RED}[오류] 웹 프론트엔드 시작 실패. 로그 확인: /tmp/eai_web.log${NC}"
    exit 1
fi
echo -e "  ${GREEN}✓${NC} 웹 애플리케이션 준비 완료: http://localhost:3000"

echo -e "\n${GREEN}==============================================================================${NC}"
echo -e "${GREEN}  🎉 모든 서비스가 성공적으로 시작되었습니다!${NC}"
echo -e "${GREEN}==============================================================================${NC}"
echo -e "  ${CYAN}• 웹 UI 접속 주소 :${NC} ${GREEN}http://localhost:3000${NC}"
echo -e "  ${CYAN}• API Swagger 문서:${NC} ${GREEN}http://127.0.0.1:8000/docs${NC}"
echo -e "  ${CYAN}• 대표 샘플 도면  :${NC} ${YELLOW}fixtures/dxf/basic_devices.dxf${NC}"
echo -e "  ${CYAN}• 시연 클릭 가이드:${NC} ${YELLOW}docs/USER_SMOKE_TEST.md${NC}"
echo -e "${GREEN}------------------------------------------------------------------------------${NC}"
echo -e "  ${YELLOW}※ 주의: 위 주소는 사용자 로컬 머신에서만 열 수 있는 로컬 전용 서버입니다.${NC}"
echo -e "  ${YELLOW}※ 서버를 종료하려면 언제든지 [Ctrl + C]를 누르세요.${NC}"
echo -e "${GREEN}==============================================================================${NC}\n"

# Keep script running to maintain child processes
while true; do
    sleep 1
done
