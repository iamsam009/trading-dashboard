#!/usr/bin/env bash
# ─── Production Health Check Script ──────────────────────
# Checks the health of all services in the production stack.
#
# Exits with 0 if all services are healthy, non-zero otherwise.
#
# Usage:
#   chmod +x healthcheck.sh
#   ./healthcheck.sh
#   ./healthcheck.sh --verbose
#   ./healthcheck.sh --json          # Output as JSON
#
# Services checked:
#   - Backend  (http://localhost:8000/health)
#   - Backend  (http://localhost:8000/ready)
#   - Nginx    (http://localhost:80/health)
#   - Frontend (http://localhost:3000)
#   - Postgres (pg_isready via docker)
#   - Redis    (redis-cli ping via docker)
#   - Prometheus (http://localhost:9090/-/healthy)
#   - Grafana    (http://localhost:3001/api/health)

set -euo pipefail

# ── Configuration ────────────────────────────────────────
BACKEND_HEALTH_URL="${BACKEND_HEALTH_URL:-http://localhost:8000/health}"
BACKEND_READY_URL="${BACKEND_READY_URL:-http://localhost:8000/ready}"
BACKEND_METRICS_URL="${BACKEND_METRICS_URL:-http://localhost:8000/metrics}"
NGINX_HEALTH_URL="${NGINX_HEALTH_URL:-http://localhost:80/health}"
FRONTEND_URL="${FRONTEND_URL:-http://localhost:3000}"
PROMETHEUS_URL="${PROMETHEUS_URL:-http://localhost:9090/-/healthy}"
GRAFANA_URL="${GRAFANA_URL:-http://localhost:3001/api/health}"
TIMEOUT="${HEALTHCHECK_TIMEOUT:-5}"
VERBOSE=false
JSON_OUTPUT=false
OVERALL_EXIT=0

# ── Parse arguments ──────────────────────────────────────
for arg in "$@"; do
    case "$arg" in
        --verbose|-v) VERBOSE=true ;;
        --json|-j)    JSON_OUTPUT=true ;;
        --help|-h)
            echo "Usage: $0 [--verbose] [--json]"
            echo "Checks health of all services in the production stack."
            exit 0
            ;;
    esac
done

# ── Helpers ──────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

declare -A RESULTS
declare -A DETAILS

log_verbose() {
    if [ "$VERBOSE" = true ]; then
        echo -e "$1"
    fi
}

check_http() {
    local name="$1"
    local url="$2"
    local expected_status="${3:-200}"

    log_verbose "  → Checking $name at $url ..."

    local response
    response=$(curl -s -o /dev/null -w "%{http_code}" \
        --max-time "$TIMEOUT" \
        --connect-timeout "$TIMEOUT" \
        "$url" 2>/dev/null) || response="000"

    if [ "$response" = "$expected_status" ]; then
        RESULTS["$name"]="PASS"
        DETAILS["$name"]="HTTP $response"
        log_verbose "    ${GREEN}✓${NC} $name: HTTP $response"
        return 0
    else
        RESULTS["$name"]="FAIL"
        DETAILS["$name"]="Expected HTTP $expected_status, got HTTP $response"
        log_verbose "    ${RED}✗${NC} $name: Expected HTTP $expected_status, got HTTP $response"
        return 1
    fi
}

check_http_json() {
    local name="$1"
    local url="$2"
    local expected_status="${3:-200}"
    local expected_field="${4:-status}"
    local expected_value="${5:-ok}"

    log_verbose "  → Checking $name at $url (expecting $expected_field=$expected_value) ..."

    local response
    response=$(curl -s --max-time "$TIMEOUT" --connect-timeout "$TIMEOUT" "$url" 2>/dev/null) || true

    if [ -z "$response" ]; then
        RESULTS["$name"]="FAIL"
        DETAILS["$name"]="No response"
        log_verbose "    ${RED}✗${NC} $name: No response"
        return 1
    fi

    # Try to extract the field value with python3 (more reliable than jq in some envs)
    local field_value
    field_value=$(echo "$response" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    keys = '$expected_field'.split('.')
    val = data
    for k in keys:
        val = val.get(k, val)
    print(val if isinstance(val, (str, bool)) else json.dumps(val))
except Exception:
    print('__PARSE_ERROR__')
" 2>/dev/null) || field_value="__ERROR__"

    if [ "$field_value" = "$expected_value" ] || [ "$field_value" = "\"$expected_value\"" ]; then
        RESULTS["$name"]="PASS"
        DETAILS["$name"]="$expected_field=$field_value"
        log_verbose "    ${GREEN}✓${NC} $name: $expected_field=$field_value"
        return 0
    else
        RESULTS["$name"]="FAIL"
        DETAILS["$name"]="Expected $expected_field=$expected_value, got $field_value"
        log_verbose "    ${RED}✗${NC} $name: Expected $expected_field=$expected_value, got $field_value"
        return 1
    fi
}

check_docker_service() {
    local service_name="$1"
    local check_name="${2:-$service_name}"

    log_verbose "  → Checking Docker service $service_name ..."

    if docker compose -f docker-compose.prod.yml ps "$service_name" 2>/dev/null | grep -q "Up\|healthy"; then
        RESULTS["$check_name"]="PASS"
        DETAILS["$check_name"]="Container running"
        log_verbose "    ${GREEN}✓${NC} $check_name: Container running"
        return 0
    else
        RESULTS["$check_name"]="FAIL"
        DETAILS["$check_name"]="Container not running or not found"
        log_verbose "    ${RED}✗${NC} $check_name: Container not running"
        return 1
    fi
}

# ── Run checks ───────────────────────────────────────────
echo "🔍 Running production health checks..."
echo ""

# 1. Backend health (liveness)
check_http_json "Backend Health" "$BACKEND_HEALTH_URL" 200 "status" "ok" || OVERALL_EXIT=1

# 2. Backend readiness (DB + Redis)
check_http_json "Backend Readiness" "$BACKEND_READY_URL" 200 "status" "ok" || OVERALL_EXIT=1

# 3. Backend metrics (Prometheus)
if check_http "Backend Metrics" "$BACKEND_METRICS_URL" 200; then
    # Verify it contains expected metrics
    metrics_body=$(curl -s --max-time "$TIMEOUT" "$BACKEND_METRICS_URL" 2>/dev/null) || true
    if echo "$metrics_body" | grep -q "http_requests_total"; then
        RESULTS["Metrics Content"]="PASS"
        DETAILS["Metrics Content"]="http_requests_total found"
        log_verbose "    ${GREEN}✓${NC} Metrics Content: http_requests_total found"
    else
        RESULTS["Metrics Content"]="FAIL"
        DETAILS["Metrics Content"]="http_requests_total not found in /metrics"
        log_verbose "    ${RED}✗${NC} Metrics Content: http_requests_total not found"
        OVERALL_EXIT=1
    fi
else
    OVERALL_EXIT=1
fi

# 4. Nginx reverse proxy
check_http_json "Nginx Proxy" "$NGINX_HEALTH_URL" 200 "status" "ok" || OVERALL_EXIT=1

# 5. Frontend
check_http "Frontend" "$FRONTEND_URL" 200 || OVERALL_EXIT=1

# 6. Docker service checks
check_docker_service "postgres" "PostgreSQL" || OVERALL_EXIT=1
check_docker_service "redis" "Redis" || OVERALL_EXIT=1
check_docker_service "backend" "Backend Container" || OVERALL_EXIT=1
check_docker_service "nginx" "Nginx Container" || OVERALL_EXIT=1
check_docker_service "frontend" "Frontend Container" || OVERALL_EXIT=1
check_docker_service "celery_worker" "Celery Worker" || OVERALL_EXIT=1
check_docker_service "celery_beat" "Celery Beat" || OVERALL_EXIT=1

# 7. Prometheus (if running)
if check_http "Prometheus" "$PROMETHEUS_URL" 200 2>/dev/null; then
    true
else
    RESULTS["Prometheus"]="SKIP"
    DETAILS["Prometheus"]="Not running or not reachable"
fi

# 8. Grafana (if running)
if check_http "Grafana" "$GRAFANA_URL" 200 2>/dev/null; then
    true
else
    RESULTS["Grafana"]="SKIP"
    DETAILS["Grafana"]="Not running or not reachable"
fi

echo ""

# ── Output ───────────────────────────────────────────────
if [ "$JSON_OUTPUT" = true ]; then
    # JSON output
    echo "{"
    echo "  \"overall\": \"$([ "$OVERALL_EXIT" -eq 0 ] && echo "PASS" || echo "FAIL")\","
    echo "  \"checks\": {"
    first=true
    for name in "${!RESULTS[@]}"; do
        if [ "$first" = true ]; then first=false; else echo ","; fi
        echo -n "    \"$name\": {\"status\": \"${RESULTS[$name]}\", \"detail\": \"${DETAILS[$name]}\"}"
    done
    echo ""
    echo "  }"
    echo "}"
else
    # Pretty output
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    printf "  %-30s %s\n" "SERVICE" "STATUS"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    for name in "${!RESULTS[@]}"; do
        status="${RESULTS[$name]}"
        icon=""
        if [ "$status" = "PASS" ]; then
            icon="${GREEN}✓${NC}"
        elif [ "$status" = "FAIL" ]; then
            icon="${RED}✗${NC}"
        else
            icon="${YELLOW}○${NC}"
        fi
        printf "  ${icon} %-28s %s\n" "$name" "$status"
        if [ "$VERBOSE" = true ] && [ -n "${DETAILS[$name]:-}" ]; then
            printf "    %s\n" "${DETAILS[$name]}"
        fi
    done
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

    if [ "$OVERALL_EXIT" -eq 0 ]; then
        echo -e "\n${GREEN}✅ All health checks passed${NC}"
    else
        echo -e "\n${RED}❌ Some health checks FAILED${NC}"
    fi
fi

exit "$OVERALL_EXIT"