#!/usr/bin/env bash
# ==============================================================================
# Electrical AI Platform - Local Server Stop Script
#
# Usage:
#   ./scripts/dev-stop.sh
# ==============================================================================

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

echo -e "${CYAN}==============================================================================${NC}"
echo -e "${CYAN}  Electrical AI Platform - 로컬 서비스 종료${NC}"
echo -e "${CYAN}==============================================================================${NC}"

# Find and kill API port 8000
API_PIDS=$(lsof -ti :8000 || true)
if [ -n "$API_PIDS" ]; then
    echo -e "${YELLOW}• 포트 8000 (API 백엔드) 프로세스 종료 중... (PIDs: $API_PIDS)${NC}"
    echo "$API_PIDS" | xargs kill -15 2>/dev/null || true
    sleep 1
    # Force kill if still alive
    API_PIDS_REMAINING=$(lsof -ti :8000 || true)
    if [ -n "$API_PIDS_REMAINING" ]; then
        echo "$API_PIDS_REMAINING" | xargs kill -9 2>/dev/null || true
    fi
    echo -e "  ${GREEN}✓${NC} 포트 8000 정리 완료"
else
    echo -e "  ${GREEN}✓${NC} 포트 8000: 실행 중인 프로세스 없음"
fi

# Find and kill Web port 3000
WEB_PIDS=$(lsof -ti :3000 || true)
if [ -n "$WEB_PIDS" ]; then
    echo -e "${YELLOW}• 포트 3000 (웹 프론트엔드) 프로세스 종료 중... (PIDs: $WEB_PIDS)${NC}"
    echo "$WEB_PIDS" | xargs kill -15 2>/dev/null || true
    sleep 1
    WEB_PIDS_REMAINING=$(lsof -ti :3000 || true)
    if [ -n "$WEB_PIDS_REMAINING" ]; then
        echo "$WEB_PIDS_REMAINING" | xargs kill -9 2>/dev/null || true
    fi
    echo -e "  ${GREEN}✓${NC} 포트 3000 정리 완료"
else
    echo -e "  ${GREEN}✓${NC} 포트 3000: 실행 중인 프로세스 없음"
fi

echo -e "\n${GREEN}[완료] 모든 로컬 서비스가 성공적으로 종료되었습니다.${NC}\n"
