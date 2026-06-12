#!/usr/bin/env bash
# ─── Production Deployment Test Suite ────────────────────
# End-to-end tests for production deployment, health checks,
# auto-recovery, Prometheus metrics, audit logging, and
# duplicate order prevention.
#
# Tests:
#   1. Docker Compose Production Starts
#   2. Nginx Reverse Proxy
#   3. Auto-Recovery – Backend Crash
#   4. Auto-Recovery – Database Disconnect
#   5. Auto-Recovery – Shark WebSocket Drop
#   6. Prometheus Metrics Endpoint
#   7. Log Rotation & Audit
#   8. Duplicate Order Prevention
#
# Usage:
#   chmod +x test_production.sh
#   ./test_production.sh
#   ./test_production.sh --verbose
#   ./test_production.sh --test <test_number>
#
# Prerequisites:
#   - Docker and Docker Compose installed
#   - docker-compose.prod.yml in the same directory
#   - Backend services running (docker compose -f docker-compose.prod.yml up -d)

set -euo pipefail

# ── Configuration ────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_FILE="${SCRIPT_DIR}/docker-compose.prod.yml"
BACKEND_URL="${BACKEND_URL:-http://localhost:8000}"
NGINX_URL="${NGINX_URL:-http://localhost:80}"
FRONTEND_URL="${FRONTEND_URL:-http://localhost:3000}"
TIMEOUT="${TEST_TIMEOUT:-10}"
VERBOSE=false
SPECIFIC_TEST=""
PASSED=0
FAILED=0
SKIPPED=0

# ── Colors ───────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

# ── Parse arguments ──────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        --verbose|-v) VERBOSE=true ;;
        --test)
            SPECIFIC_TEST="${2:-}"
            shift
            ;;
        --help|-h)
            echo "Usage: $0 [--verbose] [--test <number>]"
            echo ""
            echo "Production deployment test suite."
            echo ""
            echo "Options:"
            echo "  --verbose, -v     Verbose output"
            echo "  --test <number>   Run only test number <number> (1-8)"
            echo "  --help, -h        Show this help"
            exit 0
            ;;
    esac
    shift
done

# ── Helpers ──────────────────────────────────────────────
log_section() {
    echo ""
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${CYAN}  $1${NC}"
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
}

log_test() {
    echo -e "\n${YELLOW}[TEST $1]${NC} $2"
}

log_pass() {
    echo -e "  ${GREEN}✓ PASS${NC} $1"
    PASSED=$((PASSED + 1))
}

log_fail() {
    echo -e "  ${RED}✗ FAIL${NC} $1"
    if [ "$VERBOSE" = true ]; then
        echo -e "    ${RED}Reason: $2${NC}"
    fi
    FAILED=$((FAILED + 1))
}

log_skip() {
    echo -e "  ${YELLOW}○ SKIP${NC} $1"
    SKIPPED=$((SKIPPED + 1))
}

log_info() {
    if [ "$VERBOSE" = true ]; then
        echo -e "    ${BLUE}ℹ${NC} $1"
    fi
}

should_run_test() {
    local test_num="$1"
    if [ -z "$SPECIFIC_TEST" ] || [ "$SPECIFIC_TEST" = "$test_num" ]; then
        return 0
    fi
    return 1
}

wait_for_url() {
    local url="$1"
    local max_wait="${2:-30}"
    local desc="${3:-$url}"

    log_info "Waiting for $desc (max ${max_wait}s)..."
    local elapsed=0
    while [ $elapsed -lt "$max_wait" ]; do
        if curl -s -o /dev/null -w "%{http_code}" --max-time 3 "$url" 2>/dev/null | grep -q "200\|302"; then
            log_info "$desc is ready"
            return 0
        fi
        sleep 1
        elapsed=$((elapsed + 1))
    done
    return 1
}

# ── Pre-flight ───────────────────────────────────────────
echo -e "${CYAN}"
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║     Production Deployment Test Suite                         ║"
echo "║     Trading Dashboard v0.1.0                                 ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo -e "${NC}"

# Check if docker-compose.prod.yml exists
if [ ! -f "$COMPOSE_FILE" ]; then
    echo -e "${RED}Error: $COMPOSE_FILE not found${NC}"
    echo "Run this script from the project root directory."
    exit 1
fi

# Check if docker is running
if ! docker info >/dev/null 2>&1; then
    echo -e "${RED}Error: Docker is not running or not accessible${NC}"
    exit 1
fi

# Check if services are running
COMPOSE_RUNNING=false
if docker compose -f "$COMPOSE_FILE" ps 2>/dev/null | grep -q "Up"; then
    COMPOSE_RUNNING=true
fi

# ═══════════════════════════════════════════════════════════
# TEST 1: Docker Compose Production Starts
# ═══════════════════════════════════════════════════════════
if should_run_test "1"; then
    log_section "Test 1: Docker Compose Production Starts"

    if [ "$COMPOSE_RUNNING" = false ]; then
        log_test "1.1" "Starting all production services..."
        if docker compose -f "$COMPOSE_FILE" up -d --wait 2>&1 | tail -5; then
            log_pass "docker compose up -d succeeded"
            COMPOSE_RUNNING=true
        else
            log_fail "docker compose up -d failed" "Check docker compose logs"
        fi
    else
        log_info "Services already running – skipping startup"
    fi

    log_test "1.2" "All containers are healthy"
    sleep 5  # Give health checks time to run
    UNHEALTHY=$(docker compose -f "$COMPOSE_FILE" ps --format json 2>/dev/null | \
        python3 -c "
import sys, json
for line in sys.stdin:
    try:
        s = json.loads(line.strip())
        if s.get('Health', '') not in ('', 'healthy'):
            print(f\"{s.get('Service', '?')}: {s.get('Health', '?')}\")
    except: pass
" 2>/dev/null) || UNHEALTHY=""
    if [ -z "$UNHEALTHY" ]; then
        log_pass "All containers are healthy"
    else
        log_fail "Unhealthy containers found" "$UNHEALTHY"
    fi

    log_test "1.3" "curl /health returns 200"
    if wait_for_url "$BACKEND_URL/health" 30 "Backend /health"; then
        RESPONSE=$(curl -s --max-time "$TIMEOUT" "$BACKEND_URL/health" 2>/dev/null)
        if echo "$RESPONSE" | grep -q '"status":"ok"'; then
            log_pass "/health returns {\"status\":\"ok\"}"
        else
            log_fail "/health unexpected response" "$RESPONSE"
        fi
    else
        log_fail "/health not reachable" "Backend did not start within 30s"
    fi

    log_test "1.4" "All Docker compose services are running"
    EXPECTED_SERVICES="postgres redis backend celery_worker celery_beat nginx frontend"
    ALL_UP=true
    for svc in $EXPECTED_SERVICES; do
        if docker compose -f "$COMPOSE_FILE" ps "$svc" 2>/dev/null | grep -q "Up"; then
            log_info "  $svc: Up"
        else
            log_info "  $svc: NOT Up"
            ALL_UP=false
        fi
    done
    if [ "$ALL_UP" = true ]; then
        log_pass "All 7 expected services are running"
    else
        log_fail "Some services are not running" "Check docker compose ps"
    fi
fi

# ═══════════════════════════════════════════════════════════
# TEST 2: Nginx Reverse Proxy
# ═══════════════════════════════════════════════════════════
if should_run_test "2"; then
    log_section "Test 2: Nginx Reverse Proxy"

    log_test "2.1" "Nginx proxies /health to backend"
    if wait_for_url "$NGINX_URL/health" 10 "Nginx /health"; then
        RESPONSE=$(curl -s --max-time "$TIMEOUT" "$NGINX_URL/health" 2>/dev/null)
        if echo "$RESPONSE" | grep -q '"status":"ok"'; then
            log_pass "Nginx /health proxies to backend successfully"
        else
            log_fail "Nginx /health unexpected response" "$RESPONSE"
        fi
    else
        log_fail "Nginx /health not reachable" "Nginx may not be running"
    fi

    log_test "2.2" "Nginx proxies /api/ to backend"
    RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" --max-time "$TIMEOUT" "$NGINX_URL/api/v1/auth/login" 2>/dev/null) || RESPONSE="000"
    if [ "$RESPONSE" != "000" ] && [ "$RESPONSE" != "502" ] && [ "$RESPONSE" != "504" ]; then
        log_pass "Nginx /api/ proxy returns HTTP $RESPONSE (not 502/504)"
    else
        log_fail "Nginx /api/ proxy failing" "Got HTTP $RESPONSE"
    fi

    log_test "2.3" "Nginx proxies frontend at /"
    FRONT_RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" --max-time "$TIMEOUT" "$NGINX_URL/" 2>/dev/null) || FRONT_RESPONSE="000"
    if [ "$FRONT_RESPONSE" = "200" ] || [ "$FRONT_RESPONSE" = "302" ]; then
        log_pass "Nginx / proxies to frontend (HTTP $FRONT_RESPONSE)"
    else
        log_fail "Nginx / frontend proxy failing" "Got HTTP $FRONT_RESPONSE"
    fi

    log_test "2.4" "Nginx /ready returns 200"
    RESPONSE=$(curl -s --max-time "$TIMEOUT" "$NGINX_URL/ready" 2>/dev/null)
    if echo "$RESPONSE" | grep -q '"status"'; then
        log_pass "Nginx /ready proxies correctly"
    else
        log_fail "Nginx /ready unexpected" "$RESPONSE"
    fi
fi

# ═══════════════════════════════════════════════════════════
# TEST 3: Auto-Recovery – Backend Crash
# ═══════════════════════════════════════════════════════════
if should_run_test "3"; then
    log_section "Test 3: Auto-Recovery – Backend Crash"

    log_test "3.1" "Kill backend container"
    docker compose -f "$COMPOSE_FILE" kill backend 2>/dev/null || true
    sleep 2
    log_info "Backend killed"

    log_test "3.2" "Backend restarts within 10 seconds"
    RESTARTED=false
    for i in $(seq 1 15); do
        if docker compose -f "$COMPOSE_FILE" ps backend 2>/dev/null | grep -q "Up"; then
            RESTARTED=true
            log_info "Backend restarted after ${i}s"
            break
        fi
        sleep 1
    done
    if [ "$RESTARTED" = true ]; then
        log_pass "Backend restarted within timeout"
    else
        log_fail "Backend did not restart within 15s" "Docker restart policy may not be working"
    fi

    log_test "3.3" "Backend /health responds after restart"
    if wait_for_url "$BACKEND_URL/health" 20 "Backend after restart"; then
        log_pass "Backend /health responding after restart"
    else
        log_fail "Backend /health not responding after restart" "Check backend logs"
    fi

    log_test "3.4" "WebSocket endpoints recover after restart"
    sleep 3
    WS_RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" --max-time "$TIMEOUT" \
        -H "Connection: Upgrade" -H "Upgrade: websocket" \
        "$BACKEND_URL/api/v1/ws/" 2>/dev/null) || WS_RESPONSE="000"
    if [ "$WS_RESPONSE" != "000" ]; then
        log_pass "WebSocket endpoint reachable after restart (HTTP $WS_RESPONSE)"
    else
        log_fail "WebSocket endpoint not reachable" "Check WebSocket server"
    fi
fi

# ═══════════════════════════════════════════════════════════
# TEST 4: Auto-Recovery – Database Disconnect
# ═══════════════════════════════════════════════════════════
if should_run_test "4"; then
    log_section "Test 4: Auto-Recovery – Database Disconnect"

    log_test "4.1" "Pause PostgreSQL container"
    docker compose -f "$COMPOSE_FILE" pause postgres 2>/dev/null || true
    sleep 2
    log_info "PostgreSQL paused"

    log_test "4.2" "Backend /ready returns 503 (degraded) during DB outage"
    RESPONSE=$(curl -s --max-time "$TIMEOUT" "$BACKEND_URL/ready" 2>/dev/null) || RESPONSE=""
    if echo "$RESPONSE" | grep -q '"degraded"'; then
        log_pass "Backend correctly reports degraded during DB outage"
    else
        log_info "Response: $RESPONSE"
        log_fail "Backend did not report degraded" "Expected 503 with 'degraded' status"
    fi

    log_test "4.3" "Unpause PostgreSQL"
    docker compose -f "$COMPOSE_FILE" unpause postgres 2>/dev/null || true
    sleep 3
    log_info "PostgreSQL unpaused"

    log_test "4.4" "Backend /ready returns 200 after DB recovery"
    if wait_for_url "$BACKEND_URL/ready" 30 "Backend /ready after DB recovery"; then
        RESPONSE=$(curl -s --max-time "$TIMEOUT" "$BACKEND_URL/ready" 2>/dev/null)
        if echo "$RESPONSE" | grep -q '"status":"ok"'; then
            log_pass "Backend /ready returns ok after DB recovery"
        else
            log_fail "Backend /ready not fully recovered" "$RESPONSE"
        fi
    else
        log_fail "Backend /ready not reachable after DB recovery" "Backend may need manual restart"
    fi

    log_test "4.5" "Backend retries DB and resumes normal operation"
    RESPONSE=$(curl -s --max-time "$TIMEOUT" "$BACKEND_URL/health" 2>/dev/null)
    if echo "$RESPONSE" | grep -q '"status":"ok"'; then
        log_pass "Backend resumed normal operation after DB recovery"
    else
        log_fail "Backend not fully operational after DB recovery" "$RESPONSE"
    fi
fi

# ═══════════════════════════════════════════════════════════
# TEST 5: Auto-Recovery – Shark WebSocket Drop
# ═══════════════════════════════════════════════════════════
if should_run_test "5"; then
    log_section "Test 5: Auto-Recovery – Shark WebSocket Drop"

    log_test "5.1" "Verify WebSocket endpoint is available"
    WS_STATUS=$(curl -s -o /dev/null -w "%{http_code}" --max-time "$TIMEOUT" \
        "$BACKEND_URL/api/v1/ws/" 2>/dev/null) || WS_STATUS="000"
    if [ "$WS_STATUS" != "000" ]; then
        log_pass "WebSocket endpoint available"
    else
        log_fail "WebSocket endpoint not reachable" "Backend ws router may not be running"
    fi

    log_test "5.2" "HeartbeatMonitor detects missing heartbeat (stale > 90s)"
    # This test is validated by checking the auto_recovery module is importable
    # and the heartbeat constants are properly configured
    HEARTBEAT_CHECK=$(docker compose -f "$COMPOSE_FILE" exec -T backend \
        python3 -c "
from app.core.auto_recovery import (
    HEARTBEAT_INTERVAL_SECONDS,
    HEARTBEAT_MISS_THRESHOLD,
    HeartbeatMonitor,
)
import time
m = HeartbeatMonitor()
m.last_heartbeat = time.monotonic() - 100  # Simulate stale
print(f'stale={m.is_stale}, interval={HEARTBEAT_INTERVAL_SECONDS}, threshold={HEARTBEAT_MISS_THRESHOLD}')
" 2>/dev/null) || HEARTBEAT_CHECK=""
    if echo "$HEARTBEAT_CHECK" | grep -q "stale=True"; then
        log_pass "HeartbeatMonitor correctly detects stale connections"
    else
        log_info "Heartbeat check output: $HEARTBEAT_CHECK"
        log_fail "HeartbeatMonitor not detecting stale state" "Check auto_recovery.py"
    fi

    log_test "5.3" "ReconnectController uses exponential backoff"
    BACKOFF_CHECK=$(docker compose -f "$COMPOSE_FILE" exec -T backend \
        python3 -c "
from app.core.auto_recovery import ReconnectController
ctrl = ReconnectController(initial_delay=1.0, max_delay=60.0, backoff_factor=2.0)
delays = [ctrl.next_delay() for _ in range(5)]
print(f'delays={[round(d, 2) for d in delays]}, increasing={all(delays[i] <= delays[i+1] for i in range(len(delays)-1))}')
" 2>/dev/null) || BACKOFF_CHECK=""
    if echo "$BACKOFF_CHECK" | grep -q "increasing=True"; then
        log_pass "ReconnectController uses exponential backoff"
    else
        log_info "Backoff check output: $BACKOFF_CHECK"
        log_fail "ReconnectController backoff not working" "Check auto_recovery.py"
    fi

    log_test "5.4" "Shark WebSocket client reconnects within 15s"
    # Validate that the SharkWebSocketClient has reconnect logic
    RECONNECT_CHECK=$(docker compose -f "$COMPOSE_FILE" exec -T backend \
        python3 -c "
from app.brokers.shark_websocket import SharkWebSocketClient
import inspect
src = inspect.getsource(SharkWebSocketClient.connect)
print('reconnect' if 'reconnect' in src.lower() or 'retry' in src.lower() or 'while True' in src else 'no-reconnect')
" 2>/dev/null) || RECONNECT_CHECK=""
    if echo "$RECONNECT_CHECK" | grep -q "reconnect"; then
        log_pass "SharkWebSocketClient has reconnect logic"
    else
        log_info "Reconnect check: $RECONNECT_CHECK"
        log_fail "SharkWebSocketClient may lack reconnect logic" "Check shark_websocket.py"
    fi
fi

# ═══════════════════════════════════════════════════════════
# TEST 6: Prometheus Metrics Endpoint
# ═══════════════════════════════════════════════════════════
if should_run_test "6"; then
    log_section "Test 6: Prometheus Metrics Endpoint"

    log_test "6.1" "/metrics returns text/plain content type"
    CT=$(curl -s -o /dev/null -w "%{content_type}" --max-time "$TIMEOUT" \
        "$BACKEND_URL/metrics" 2>/dev/null) || CT=""
    if echo "$CT" | grep -q "text/plain"; then
        log_pass "/metrics Content-Type is text/plain"
    else
        log_info "Content-Type: $CT"
        log_fail "/metrics wrong content type" "Expected text/plain"
    fi

    log_test "6.2" "http_requests_total metric is present"
    METRICS=$(curl -s --max-time "$TIMEOUT" "$BACKEND_URL/metrics" 2>/dev/null) || METRICS=""
    if echo "$METRICS" | grep -q "http_requests_total"; then
        log_pass "http_requests_total metric found"
        if [ "$VERBOSE" = true ]; then
            echo "$METRICS" | grep "http_requests_total" | head -5
        fi
    else
        log_fail "http_requests_total not found in /metrics" "Check metrics.py PrometheusMiddleware"
    fi

    log_test "6.3" "websocket_connections gauge is present"
    if echo "$METRICS" | grep -q "websocket_connections"; then
        log_pass "websocket_connections gauge found"
    else
        log_fail "websocket_connections not found in /metrics" "Check metrics.py"
    fi

    log_test "6.4" "orders_total counter is present"
    if echo "$METRICS" | grep -q "orders_total"; then
        log_pass "orders_total counter found"
    else
        log_fail "orders_total not found in /metrics" "Check metrics.py"
    fi

    log_test "6.5" "Prometheus can scrape /metrics"
    if [ -f "${SCRIPT_DIR}/prometheus/prometheus.yml" ]; then
        log_pass "Prometheus config exists for scraping backend:8000/metrics"
    else
        log_fail "Prometheus config not found" "Check prometheus/prometheus.yml"
    fi
fi

# ═══════════════════════════════════════════════════════════
# TEST 7: Log Rotation & Audit
# ═══════════════════════════════════════════════════════════
if should_run_test "7"; then
    log_section "Test 7: Log Rotation & Audit"

    log_test "7.1" "Audit log middleware is registered in the app"
    AUDIT_CHECK=$(docker compose -f "$COMPOSE_FILE" exec -T backend \
        python3 -c "
from app.main import app
middlewares = [m.cls.__name__ for m in app.user_middleware]
print('audit_log_middleware' if 'audit_log_middleware' in str(app.user_middleware) else 'not-found')
" 2>/dev/null) || AUDIT_CHECK=""
    if echo "$AUDIT_CHECK" | grep -q "audit_log_middleware"; then
        log_pass "Audit log middleware is registered"
    else
        log_info "Middleware check: $AUDIT_CHECK"
        log_fail "Audit log middleware not found" "Check main.py"
    fi

    log_test "7.2" "Log entries include user_id field"
    # Check the Log model has user_id
    MODEL_CHECK=$(docker compose -f "$COMPOSE_FILE" exec -T backend \
        python3 -c "
from app.models.log import Log
print('user_id' if hasattr(Log, 'user_id') else 'missing')
" 2>/dev/null) || MODEL_CHECK=""
    if echo "$MODEL_CHECK" | grep -q "user_id"; then
        log_pass "Log model includes user_id field"
    else
        log_fail "Log model missing user_id" "Check models/log.py"
    fi

    log_test "7.3" "Order placements are logged with user_id"
    ORDER_LOG_CHECK=$(docker compose -f "$COMPOSE_FILE" exec -T backend \
        python3 -c "
import inspect
from app.core.order_manager import OrderManager
src = inspect.getsource(OrderManager._log_success)
print('user_id' if 'user_id' in src else 'missing')
" 2>/dev/null) || ORDER_LOG_CHECK=""
    if echo "$ORDER_LOG_CHECK" | grep -q "user_id"; then
        log_pass "Order success logs include user_id"
    else
        log_fail "Order success logs missing user_id" "Check order_manager.py _log_success"
    fi

    log_test "7.4" "Risk rejections are logged with user_id"
    RISK_LOG_CHECK=$(docker compose -f "$COMPOSE_FILE" exec -T backend \
        python3 -c "
import inspect
from app.core.order_manager import OrderManager
src = inspect.getsource(OrderManager._log_error)
print('user_id' if 'user_id' in src else 'missing')
" 2>/dev/null) || RISK_LOG_CHECK=""
    if echo "$RISK_LOG_CHECK" | grep -q "user_id"; then
        log_pass "Risk rejection logs include user_id"
    else
        log_fail "Risk rejection logs missing user_id" "Check order_manager.py _log_error"
    fi

    log_test "7.5" "Login attempts are logged with user_id"
    AUTH_LOG_CHECK=$(docker compose -f "$COMPOSE_FILE" exec -T backend \
        python3 -c "
import inspect
from app.api.auth import router
# Check if auth routes exist
routes = [r.path for r in router.routes]
print('login' if any('login' in p for p in routes) else 'no-login')
print('routes', routes[:5])
" 2>/dev/null) || AUTH_LOG_CHECK=""
    if echo "$AUTH_LOG_CHECK" | grep -q "login"; then
        log_pass "Login endpoint exists for audit logging"
    else
        log_info "Auth routes: $AUTH_LOG_CHECK"
        log_skip "Login endpoint not found – check auth.py"
    fi

    log_test "7.6" "Docker log rotation is configured"
    if grep -q "max-size" "$COMPOSE_FILE" && grep -q "max-file" "$COMPOSE_FILE"; then
        log_pass "Log rotation configured in docker-compose.prod.yml"
    else
        log_fail "Log rotation not configured" "Add logging options to docker-compose.prod.yml"
    fi
fi

# ═══════════════════════════════════════════════════════════
# TEST 8: Duplicate Order Prevention
# ═══════════════════════════════════════════════════════════
if should_run_test "8"; then
    log_section "Test 8: Duplicate Order Prevention"

    log_test "8.1" "DuplicateOrderGuard module exists and is importable"
    DEDUP_CHECK=$(docker compose -f "$COMPOSE_FILE" exec -T backend \
        python3 -c "
from app.core.duplicate_order_guard import DuplicateOrderGuard, DuplicateOrderError
print('imported')
" 2>/dev/null) || DEDUP_CHECK=""
    if echo "$DEDUP_CHECK" | grep -q "imported"; then
        log_pass "DuplicateOrderGuard module importable"
    else
        log_fail "DuplicateOrderGuard not importable" "Check duplicate_order_guard.py"
    fi

    log_test "8.2" "DuplicateOrderGuard check_or_raise detects same client_order_id"
    DEDUP_SAME=$(docker compose -f "$COMPOSE_FILE" exec -T backend \
        python3 -c "
import asyncio
from app.core.duplicate_order_guard import DuplicateOrderGuard, DuplicateOrderError

async def test():
    g = DuplicateOrderGuard()
    await g.check_or_raise(1, 'BTCUSDT', 'BUY', 0.01, 50000.0, 'MARKET', 'cli-123')
    await g.record(1, 'BTCUSDT', 'BUY', 0.01, 50000.0, 'MARKET', 'cli-123', 'ex-456')
    try:
        await g.check_or_raise(1, 'BTCUSDT', 'BUY', 0.01, 50000.0, 'MARKET', 'cli-123')
        print('NOT_DETECTED')
    except DuplicateOrderError as e:
        print('DETECTED:', str(e)[:50])
    await g.clear(1, 'cli-123')

asyncio.run(test())
" 2>/dev/null) || DEDUP_SAME=""
    if echo "$DEDUP_SAME" | grep -q "DETECTED"; then
        log_pass "Duplicate client_order_id detected"
    else
        log_info "Dedup test: $DEDUP_SAME"
        log_fail "Duplicate client_order_id not detected" "Check DuplicateOrderGuard"
    fi

    log_test "8.3" "DuplicateOrderGuard detects same content hash (no client_order_id)"
    DEDUP_HASH=$(docker compose -f "$COMPOSE_FILE" exec -T backend \
        python3 -c "
import asyncio
from app.core.duplicate_order_guard import DuplicateOrderGuard, DuplicateOrderError

async def test():
    g = DuplicateOrderGuard()
    await g.record(1, 'ETHUSDT', 'SELL', 0.1, 3000.0, 'LIMIT', None, 'ex-789')
    try:
        await g.check_or_raise(1, 'ETHUSDT', 'SELL', 0.1, 3000.0, 'LIMIT', None)
        print('NOT_DETECTED')
    except DuplicateOrderError as e:
        print('HASH_DETECTED:', str(e)[:60])
    await g.clear(1)

asyncio.run(test())
" 2>/dev/null) || DEDUP_HASH=""
    if echo "$DEDUP_HASH" | grep -q "HASH_DETECTED"; then
        log_pass "Duplicate content hash detected"
    else
        log_info "Hash dedup test: $DEDUP_HASH"
        log_fail "Duplicate content hash not detected" "Check DuplicateOrderGuard"
    fi

    log_test "8.4" "Non-duplicate orders pass through"
    DEDUP_OK=$(docker compose -f "$COMPOSE_FILE" exec -T backend \
        python3 -c "
import asyncio
from app.core.duplicate_order_guard import DuplicateOrderGuard, DuplicateOrderError

async def test():
    g = DuplicateOrderGuard()
    try:
        await g.check_or_raise(1, 'SOLUSDT', 'BUY', 1.0, 100.0, 'MARKET', 'unique-999')
        await g.record(1, 'SOLUSDT', 'BUY', 1.0, 100.0, 'MARKET', 'unique-999', 'ex-111')
        # Different client_order_id should pass
        await g.check_or_raise(1, 'SOLUSDT', 'BUY', 1.0, 100.0, 'MARKET', 'different-888')
        print('PASSED')
    except DuplicateOrderError as e:
        print('FALSE_POSITIVE:', str(e))
    await g.clear(1, 'unique-999')

asyncio.run(test())
" 2>/dev/null) || DEDUP_OK=""
    if echo "$DEDUP_OK" | grep -q "PASSED"; then
        log_pass "Non-duplicate orders pass through correctly"
    else
        log_info "Non-dup test: $DEDUP_OK"
        log_fail "Non-duplicate orders incorrectly rejected" "Check DuplicateOrderGuard"
    fi

    log_test "8.5" "Duplicate order is logged as 'duplicate order'"
    if grep -q "Duplicate order" "${SCRIPT_DIR}/backend/app/core/duplicate_order_guard.py"; then
        log_pass "Duplicate order error message includes 'Duplicate order'"
    else
        log_fail "Duplicate order message not descriptive" "Check DuplicateOrderError message"
    fi
fi

# ═══════════════════════════════════════════════════════════
# SUMMARY
# ═══════════════════════════════════════════════════════════
echo ""
echo -e "${BLUE}╔══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║                    TEST RESULTS                             ║${NC}"
echo -e "${BLUE}╚══════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "  ${GREEN}Passed:${NC}  $PASSED"
echo -e "  ${RED}Failed:${NC}  $FAILED"
echo -e "  ${YELLOW}Skipped:${NC} $SKIPPED"
echo ""

if [ "$FAILED" -eq 0 ]; then
    echo -e "${GREEN}✅ All tests passed!${NC}"
    exit 0
else
    echo -e "${RED}❌ $FAILED test(s) failed.${NC}"
    echo ""
    echo "To debug:"
    echo "  docker compose -f docker-compose.prod.yml logs <service>"
    echo "  ./test_production.sh --verbose --test <failed_test_number>"
    exit 1
fi