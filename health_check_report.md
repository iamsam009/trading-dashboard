# Trading Dashboard - End-to-End Health Check Report

**Generated:** 2026-06-13T13:42:00Z
**Target:** AWS EC2 `ip-172-31-34-58` (Public: `65.2.22.19`)
**Repository:** `iamsam009/trading-dashboard`

---

## JSON Report

```json
{
  "overall_status": "PARTIAL",
  "timestamp": "2026-06-13T13:42:00Z",
  "frontend": {
    "status": "PARTIAL",
    "framework": "Next.js 14.2.35 (App Router)",
    "output_mode": "standalone",
    "routes": {
      "total": 3,
      "registered": ["/dashboard", "/backtest", "/strategies"],
      "missing": ["/login", "/signup", "/profile"],
      "details": {
        "/": {
          "file": "frontend/src/app/layout.tsx",
          "type": "root_layout",
          "description": "Root HTML layout with metadata 'Trading Dashboard'"
        },
        "/dashboard": {
          "file": "frontend/src/app/dashboard/page.tsx",
          "type": "page",
          "directive": "use client",
          "tabs": ["Overview", "Positions", "Strategies", "TradeLog", "Analytics", "Risk"],
          "api_calls": ["GET /api/v1/dashboard/overview"],
          "components": ["Navbar", "Sidebar", "EquityChart", "MetricsCards", "PositionsTable", "TradeHistory", "RiskPanel"]
        },
        "/backtest": {
          "file": "frontend/src/app/backtest/page.tsx",
          "type": "page",
          "directive": "use client",
          "components": ["Navbar", "EquityCurveChart", "MetricsTable", "TradesTable"]
        },
        "/strategies": {
          "file": "frontend/src/app/strategies/page.tsx",
          "type": "page",
          "directive": "use client",
          "components": ["Navbar", "StrategyCard", "StrategyModal", "JsonEditor"]
        }
      }
    },
    "state_management": {
      "stores": 2,
      "details": [
        {"name": "useDashboardStore", "file": "frontend/src/store/dashboardStore.ts", "type": "WebSocket-driven"},
        {"name": "useTradingStore", "file": "frontend/src/store/useTradingStore.ts", "type": "REST + WebSocket"}
      ],
      "issue": "Two overlapping Zustand stores with duplicate types (Position, Balance)"
    },
    "api_configuration": {
      "base_url": "/api/v1",
      "file": "frontend/src/lib/api.ts",
      "strategy": "Relative URL via Next.js rewrites",
      "rewrites": {
        "file": "frontend/next.config.js",
        "source": "/api/:path*",
        "destination": "http://backend:8000/api/:path*"
      }
    },
    "authentication_ui": {
      "status": "MISSING",
      "login_page": false,
      "signup_page": false,
      "auth_context": false,
      "route_guard_middleware": false,
      "token_storage": "localStorage (no HttpOnly cookie)",
      "token_extraction": "Inline axios interceptors in each page"
    },
    "websocket": {
      "hook": "frontend/src/hooks/useWebSocket.ts",
      "url_builder": "NEXT_PUBLIC_WS_URL + /user_id",
      "reconnect": "Exponential backoff (1s-30s)",
      "heartbeat": "ping/pong every 25s client-side"
    },
    "test_coverage": {
      "component_tests": ["Dashboard", "PositionsTable", "RiskPanel", "TradeHistory", "StrategyRunner", "StrategyUpload", "AlertNotifications", "MobileResponsive"],
      "hook_tests": ["useWebSocket"],
      "test_framework": "Jest + React Testing Library"
    }
  },
  "backend": {
    "status": "PARTIAL",
    "framework": "FastAPI (Python 3.11)",
    "total_endpoints": 25,
    "routers": {
      "auth": {
        "prefix": "/api/v1/auth",
        "endpoints": [
          {"method": "POST", "path": "/signup", "auth": false},
          {"method": "POST", "path": "/login", "auth": false},
          {"method": "POST", "path": "/refresh", "auth": false},
          {"method": "GET", "path": "/me", "auth": true}
        ]
      },
      "api_keys": {
        "prefix": "/api/v1/api-keys",
        "endpoints": [
          {"method": "POST", "path": "/", "auth": true},
          {"method": "GET", "path": "/", "auth": true},
          {"method": "GET", "path": "/{key_id}", "auth": true},
          {"method": "PUT", "path": "/{key_id}", "auth": true},
          {"method": "DELETE", "path": "/{key_id}", "auth": true}
        ]
      },
      "backtest": {
        "prefix": "/api/v1/backtest",
        "endpoints": [
          {"method": "POST", "path": "/", "auth": true, "async": true, "delegates_to": "celery"},
          {"method": "GET", "path": "/{task_id}/result", "auth": true}
        ]
      },
      "dashboard": {
        "prefix": "/api/v1/dashboard",
        "endpoints": [
          {"method": "GET", "path": "/overview", "auth": true},
          {"method": "GET", "path": "/balance", "auth": true},
          {"method": "GET", "path": "/positions", "auth": true},
          {"method": "GET", "path": "/strategies", "auth": true}
        ]
      },
      "risk": {
        "prefix": "/api/v1/risk",
        "endpoints": [
          {"method": "GET", "path": "/settings", "auth": true},
          {"method": "PUT", "path": "/settings", "auth": true},
          {"method": "POST", "path": "/check", "auth": true},
          {"method": "POST", "path": "/kill-switch", "auth": true},
          {"method": "GET", "path": "/status", "auth": true}
        ]
      },
      "strategies": {
        "prefix": "/api/v1/strategies",
        "endpoints": [
          {"method": "POST", "path": "/", "auth": true},
          {"method": "GET", "path": "/", "auth": true},
          {"method": "GET", "path": "/{strategy_id}", "auth": true},
          {"method": "PUT", "path": "/{strategy_id}", "auth": true},
          {"method": "DELETE", "path": "/{strategy_id}", "auth": true},
          {"method": "POST", "path": "/{strategy_id}/validate", "auth": true}
        ]
      },
      "trading": {
        "prefix": "/api/v1/trading",
        "endpoints": [
          {"method": "GET", "path": "/balance", "auth": true},
          {"method": "GET", "path": "/positions", "auth": true},
          {"method": "GET", "path": "/orders", "auth": true},
          {"method": "POST", "path": "/manual-order", "auth": true, "admin_only": true}
        ]
      },
      "websocket": {
        "prefix": "/api/v1/ws",
        "endpoints": [
          {"method": "WS", "path": "/{user_id}", "auth": false, "note": "JWT validated inside handler"}
        ]
      }
    },
    "core_modules": {
      "security": {
        "file": "backend/app/core/security.py",
        "features": ["JWT access/refresh tokens", "Fernet API key encryption", "bcrypt password hashing"],
        "access_token_expiry": "24 hours (default)"
      },
      "risk_manager": {
        "file": "backend/app/core/risk_manager.py",
        "features": ["Daily loss limit", "Max drawdown", "Trailing stops", "Kill switch", "Position monitoring"]
      },
      "order_manager": {
        "file": "backend/app/core/order_manager.py",
        "features": ["Manual order placement", "Balance check", "Position tracking", "Trade recording"]
      },
      "duplicate_guard": {
        "file": "backend/app/core/duplicate_order_guard.py",
        "features": ["Redis-based order deduplication", "Idempotency key support"]
      },
      "strategy_engine": {
        "file": "backend/app/engine/strategy_engine.py",
        "features": ["Technical indicators (EMA, SMA, RSI, MACD, BB, ATR, VWAP)", "Rolling window candles", "Signal generation"]
      },
      "strategy_validator": {
        "file": "backend/app/core/strategy_validator.py",
        "features": ["JSON schema validation", "Semantic indicator validation"]
      }
    },
    "celery_tasks": {
      "backtest": "backend/app/tasks/backtest.py - Async backtest with synthetic/cached OHLCV",
      "daily_reports": "backend/app/tasks/reports.py - Daily PnL aggregation and performance snapshots",
      "risk_monitor": "backend/app/tasks/risk_monitor.py - Periodic risk cycle evaluation"
    },
    "test_coverage": {
      "unit_tests": ["auth", "strategies", "shark_client", "config", "models", "health", "celery", "order_manager", "risk_manager", "strategy_engine", "market_pipeline", "websocket"],
      "e2e_tests": ["full_user_journey", "duplicate_order", "multiple_strategies", "risk_settings_flow"],
      "total_test_files": 15,
      "status": "83/83 passing"
    }
  },
  "database": {
    "status": "PASS",
    "engine": "PostgreSQL 16 (Alpine)",
    "async_driver": "asyncpg via SQLAlchemy async",
    "orm": "SQLAlchemy 2.0 (declarative, Mapped types)",
    "migrations": {
      "tool": "Alembic",
      "current_head": "0001_initial_migration",
      "auto_run": "CMD in Dockerfile (development docker-compose.yml only)"
    },
    "tables": {
      "users": {
        "columns": ["id", "email", "hashed_password", "is_active", "created_at", "updated_at"],
        "indexes": ["ix_users_email (unique)"]
      },
      "api_keys": {
        "columns": ["id", "user_id", "exchange", "api_key_encrypted", "api_secret_encrypted", "passphrase_encrypted", "label", "is_active", "created_at"],
        "indexes": ["ix_api_keys_user_id"],
        "foreign_keys": ["user_id → users.id (CASCADE)"]
      },
      "strategies": {
        "columns": ["id", "user_id", "name", "description", "json_definition (JSONB)", "is_active", "version", "tags (JSONB)", "backtest_results (JSONB)", "created_at", "updated_at"],
        "indexes": ["ix_strategies_user_id"],
        "foreign_keys": ["user_id → users.id (CASCADE)"]
      },
      "trades": {
        "columns": ["id", "user_id", "strategy_id", "symbol", "side", "order_type", "quantity", "price", "stop_price", "pnl", "pnl_percent", "fees", "status", "exchange_order_id", "client_order_id", "executed_at", "closed_at", "created_at"],
        "indexes": ["ix_trades_user_id", "ix_trades_strategy_id", "ix_trades_symbol", "ix_trades_exchange_order_id"],
        "foreign_keys": ["user_id → users.id (CASCADE)", "strategy_id → strategies.id (SET NULL)"]
      },
      "positions": {
        "columns": ["id", "user_id", "strategy_id", "symbol", "side", "entry_price", "mark_price", "quantity", "leverage", "unrealized_pnl", "realized_pnl", "liquidation_price", "status", "updated_at", "opened_at", "closed_at"],
        "indexes": ["ix_positions_user_id", "ix_positions_strategy_id", "ix_positions_symbol"],
        "foreign_keys": ["user_id → users.id (CASCADE)", "strategy_id → strategies.id (SET NULL)"]
      },
      "risk_settings": {
        "columns": ["id", "user_id", "max_position_size", "max_leverage", "max_daily_loss", "max_drawdown_percent", "trailing_stop_percent", "kill_switch_engaged", "kill_switch_reason", "created_at", "updated_at"],
        "indexes": ["ix_risk_settings_user_id (unique)"],
        "foreign_keys": ["user_id → users.id (CASCADE)"],
        "unique_constraint": ["user_id"]
      },
      "logs": {
        "columns": ["id", "user_id", "level", "message", "category", "metadata (JSONB)", "created_at"],
        "indexes": ["ix_logs_user_id", "ix_logs_category", "ix_logs_created_at"],
        "foreign_keys": ["user_id → users.id (CASCADE)"]
      },
      "performance_stats": {
        "columns": ["id", "user_id", "snapshot_date", "total_pnl", "total_pnl_percent", "total_trades", "winning_trades", "losing_trades", "win_rate", "profit_factor", "sharpe_ratio", "max_drawdown_percent", "equity_curve (JSONB)", "total_fees", "created_at", "updated_at"],
        "indexes": ["ix_performance_stats_user_id"],
        "foreign_keys": ["user_id → users.id (CASCADE)"]
      }
    },
    "connection_pool": {
      "config": "backend/app/db/base.py",
      "pool_size": "default (5)",
      "max_overflow": "default (10)",
      "session_factory": "async_sessionmaker"
    }
  },
  "infrastructure": {
    "status": "PARTIAL",
    "orchestration": "Docker Compose v3.8",
    "services": {
      "development": {
        "compose_file": "docker-compose.yml",
        "services": ["postgres", "redis", "backend", "celery_worker", "celery_beat", "nginx", "frontend"]
      },
      "production": {
        "compose_file": "docker-compose.prod.yml",
        "services": ["postgres", "redis", "backend", "celery_worker", "celery_beat", "nginx", "frontend", "prometheus", "grafana"]
      }
    },
    "dockerfiles": {
      "backend": {
        "file": "backend/Dockerfile",
        "base": "python:3.11-slim",
        "stages": 2,
        "user": "appuser (non-root)",
        "healthcheck": "curl -f http://localhost:8000/health",
        "tls_fix": "ca-certificates + openssl installed in runtime"
      },
      "frontend": {
        "file": "frontend/Dockerfile",
        "base": "node:20-alpine",
        "stages": 2,
        "user": "nextjs (non-root)",
        "output": "standalone",
        "build_args": ["NEXT_PUBLIC_API_BASE_URL", "NEXT_PUBLIC_WS_URL"]
      }
    },
    "nginx": {
      "image": "nginx:1.25-alpine",
      "config": "nginx/conf.d/default.conf",
      "dns_resolver": "127.0.0.11 (Docker internal)",
      "routes": {
        "/api/": "→ backend:8000 (rate limited: burst=20)",
        "/ws/": "→ backend:8000 (24h timeout for WebSocket)",
        "/health": "→ backend:8000",
        "/ready": "→ backend:8000",
        "/docs": "→ backend:8000",
        "/openapi.json": "→ backend:8000",
        "/": "→ frontend:3000"
      }
    },
    "environment_variables": {
      "critical": ["DATABASE_URL", "REDIS_URL", "SHARK_API_KEY", "SHARK_API_SECRET", "SECRET_KEY", "ENCRYPTION_KEY"],
      "optional": ["SHARK_BASE_URL", "SHARK_WS_URL", "SHARK_SSL_VERIFY", "ENVIRONMENT", "LOG_LEVEL", "NEXT_PUBLIC_API_BASE_URL", "NEXT_PUBLIC_WS_URL"]
    },
    "networking": {
      "docker_network": "trading_net (bridge driver)",
      "exposed_ports": {
        "80": "nginx",
        "443": "nginx (SSL)",
        "3000": "frontend (Next.js)",
        "5432": "postgres",
        "6379": "redis",
        "8000": "backend (FastAPI)",
        "9090": "prometheus",
        "3001": "grafana"
      }
    }
  },
  "authentication": {
    "status": "PARTIAL",
    "flow": {
      "signup": {
        "endpoint": "POST /api/v1/auth/signup",
        "input": {"email": "EmailStr", "password": "str (min 8, max 128)"},
        "output": {"access_token": "JWT", "refresh_token": "JWT", "token_type": "bearer"},
        "password_hashing": "bcrypt (via passlib)",
        "issues": ["Uses db.flush() instead of db.commit() - transaction may not persist"]
      },
      "login": {
        "endpoint": "POST /api/v1/auth/login",
        "input": {"email": "EmailStr", "password": "str"},
        "output": {"access_token": "JWT", "refresh_token": "JWT", "token_type": "bearer"}
      },
      "refresh": {
        "endpoint": "POST /api/v1/auth/refresh",
        "input": {"refresh_token": "str"},
        "output": {"access_token": "JWT", "refresh_token": "JWT", "token_type": "bearer"},
        "validation": "Verifies token type is 'refresh'"
      },
      "token_verification": {
        "method": "OAuth2PasswordBearer + JWT decode",
        "dependency": "get_current_user in backend/app/deps.py",
        "token_type_check": "Rejects refresh tokens used as access tokens"
      }
    },
    "jwt_config": {
      "algorithm": "HS256",
      "access_token_expiry": "1440 minutes (24 hours, configurable)",
      "refresh_token_expiry": "10080 minutes (7 days)",
      "secret_key": "From SECRET_KEY env var"
    },
    "api_key_encryption": {
      "method": "Fernet symmetric encryption",
      "key": "From ENCRYPTION_KEY env var (base64-encoded 32-byte key)"
    }
  },
  "critical_errors": [
    {
      "id": "CE-001",
      "severity": "HIGH",
      "category": "authentication_ui",
      "title": "No login/signup pages in frontend",
      "description": "The frontend has no /login or /signup routes. Users cannot authenticate through the UI. There is no auth context provider, no middleware.ts for route protection, and unauthenticated users can access /dashboard directly.",
      "files": ["frontend/src/app/"],
      "impact": "Users must authenticate via API directly (curl/Postman) to obtain tokens. Dashboard pages will fail silently with 401 errors.",
      "fix": "Create /login and /signup pages with form components, add AuthContext provider, add middleware.ts for route protection"
    },
    {
      "id": "CE-002",
      "severity": "HIGH",
      "category": "cors",
      "title": "CORS hardcoded to localhost origins",
      "description": "backend/app/main.py:93 sets allow_origins=[\"http://localhost:3000\", \"http://localhost\"]. When accessed from EC2 public IP (65.2.22.19) or any domain, CORS preflight requests will fail.",
      "files": ["backend/app/main.py:93"],
      "impact": "Browser access from external IPs/domains will be blocked by CORS policy. API calls from the frontend served on a different origin will fail.",
      "fix": "Make CORS origins configurable via settings (e.g., ALLOWED_ORIGINS env var) or use allow_origin_regex"
    },
    {
      "id": "CE-003",
      "severity": "MEDIUM",
      "category": "docker_compose",
      "title": "docker-compose.prod.yml overrides CMD without migrations",
      "description": "The production compose file overrides the backend command with 'uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4 --log-level info', which does NOT include PYTHONPATH=/app or alembic upgrade head. Database migrations will not run on production deployment.",
      "files": ["docker-compose.prod.yml:141"],
      "impact": "New deployments or schema changes will not apply migrations automatically, causing 'relation does not exist' errors.",
      "fix": "Change prod command to: sh -c \"PYTHONPATH=/app alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4 --log-level info\""
    },
    {
      "id": "CE-004",
      "severity": "LOW",
      "category": "api",
      "title": "tokenUrl mismatch in OAuth2PasswordBearer",
      "description": "backend/app/deps.py:29 sets tokenUrl=\"/auth/login\" but the actual login endpoint is /api/v1/auth/login (due to the /api/v1 router prefix).",
      "files": ["backend/app/deps.py:29"],
      "impact": "OpenAPI/Swagger docs 'Authorize' button will point to wrong URL, making Swagger UI auth non-functional.",
      "fix": "Change tokenUrl to \"/api/v1/auth/login\""
    }
  ],
  "warnings": [
    {
      "id": "W-001",
      "severity": "MEDIUM",
      "category": "auth",
      "title": "Signup uses db.flush() instead of db.commit()",
      "description": "backend/app/api/auth.py:49 uses await db.flush() after adding user. The transaction is not explicitly committed, relying on FastAPI's implicit commit behavior. If an exception occurs before implicit commit, the user record may be lost.",
      "files": ["backend/app/api/auth.py:49"],
      "recommendation": "Add await db.commit() after await db.refresh(user)"
    },
    {
      "id": "W-002",
      "severity": "MEDIUM",
      "category": "security",
      "title": "Insecure default SECRET_KEY",
      "description": "backend/app/config.py:45 defaults secret_key to 'change-me-to-a-random-secret-key'. While overridable via env var, this is a security risk if the env var is not set.",
      "files": ["backend/app/config.py:45"],
      "recommendation": "Use a required field with no default, or generate a random key at startup if not provided"
    },
    {
      "id": "W-003",
      "severity": "MEDIUM",
      "category": "nginx",
      "title": "Missing limit_req_zone definition",
      "description": "nginx/conf.d/default.conf:18 references 'limit_req zone=api burst=20 nodelay' but no 'limit_req_zone' directive is defined in nginx.conf. This will cause nginx to fail on startup or silently ignore the rate limit.",
      "files": ["nginx/nginx.conf", "nginx/conf.d/default.conf:18"],
      "recommendation": "Add 'limit_req_zone $binary_remote_addr zone=api:10m rate=10r/s;' to nginx.conf http block"
    },
    {
      "id": "W-004",
      "severity": "LOW",
      "category": "frontend",
      "title": "Duplicate state stores with overlapping types",
      "description": "Two Zustand stores (dashboardStore.ts and useTradingStore.ts) both define Position, Balance, and Strategy types with different shapes. This creates maintenance burden and potential inconsistencies.",
      "files": ["frontend/src/store/dashboardStore.ts", "frontend/src/store/useTradingStore.ts"],
      "recommendation": "Consolidate into a single store or extract shared types to a types/ directory"
    },
    {
      "id": "W-005",
      "severity": "LOW",
      "category": "frontend",
      "title": "Inline axios interceptors duplicated across pages",
      "description": "The auth token extraction from localStorage and response error handling is duplicated in dashboard/page.tsx, backtest/page.tsx, and strategies/page.tsx instead of using the shared api.ts instance.",
      "files": ["frontend/src/app/dashboard/page.tsx:76-98", "frontend/src/app/backtest/page.tsx:76-98", "frontend/src/app/strategies/page.tsx:107-129"],
      "recommendation": "Remove duplicate interceptors; use the shared api instance from lib/api.ts"
    },
    {
      "id": "W-006",
      "severity": "LOW",
      "category": "docker",
      "title": "Redundant alembic COPY in Dockerfile",
      "description": "backend/Dockerfile copies all files at line 45 (COPY . .), then re-copies alembic files at lines 56-58. The second COPY is redundant.",
      "files": ["backend/Dockerfile:56-58"],
      "recommendation": "Remove lines 56-58 since alembic files are already included by line 45"
    }
  ],
  "recommended_fixes": [
    {
      "priority": "CRITICAL",
      "id": "FIX-01",
      "title": "Fix production docker-compose.prod.yml missing migrations",
      "action": "Change backend command in docker-compose.prod.yml to include PYTHONPATH=/app and alembic upgrade head before uvicorn",
      "file": "docker-compose.prod.yml",
      "line": 141,
      "current": "uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4 --log-level info",
      "replacement": "sh -c \"PYTHONPATH=/app alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4 --log-level info\""
    },
    {
      "priority": "HIGH",
      "id": "FIX-02",
      "title": "Fix CORS for external/EC2 access",
      "action": "Make CORS origins configurable via Settings/env var",
      "file": "backend/app/main.py",
      "line": 93,
      "current_code": "allow_origins=[\"http://localhost:3000\", \"http://localhost\"]",
      "replacement": "Add ALLOWED_ORIGINS to config.py and use it dynamically"
    },
    {
      "priority": "HIGH",
      "id": "FIX-03",
      "title": "Create frontend authentication pages",
      "action": ["Create src/app/login/page.tsx with login form", "Create src/app/signup/page.tsx with signup form", "Add AuthContext provider for token management", "Add src/middleware.ts for route protection"],
      "files": ["frontend/src/app/login/page.tsx (new)", "frontend/src/app/signup/page.tsx (new)"]
    },
    {
      "priority": "MEDIUM",
      "id": "FIX-04",
      "title": "Fix signup transaction handling",
      "action": "Add await db.commit() after db.refresh(user) in signup endpoint",
      "file": "backend/app/api/auth.py",
      "line": 51,
      "insert_after": "await db.refresh(user)",
      "add": "await db.commit()"
    },
    {
      "priority": "MEDIUM",
      "id": "FIX-05",
      "title": "Fix tokenUrl for Swagger docs",
      "action": "Change tokenUrl to include the full API prefix path",
      "file": "backend/app/deps.py",
      "line": 29,
      "current": "tokenUrl=\"/auth/login\"",
      "replacement": "tokenUrl=\"/api/v1/auth/login\""
    },
    {
      "priority": "LOW",
      "id": "FIX-06",
      "title": "Add rate limit zone to nginx.conf",
      "action": "Add limit_req_zone directive to nginx http block",
      "file": "nginx/nginx.conf",
      "add_after_line": 12,
      "add": "limit_req_zone $binary_remote_addr zone=api:10m rate=10r/s;"
    }
  ],
  "root_cause_analysis": [
    {
      "issue": "Dashboard 500 error (resolved)",
      "root_cause": "NEXT_PUBLIC_API_BASE_URL was baked at build time as localhost:8000 instead of backend:8000. docker-compose.yml was missing build.args for frontend service, so the Next.js standalone build had the wrong backend URL hardcoded.",
      "resolution": "Added build.args to docker-compose.yml frontend service with NEXT_PUBLIC_API_BASE_URL=http://backend:8000 and NEXT_PUBLIC_WS_URL=ws://backend:8000/ws"
    },
    {
      "issue": "Dashboard 404 error (resolved)",
      "root_cause": "Nginx container was not connected to trading_net Docker network. It was in a restart loop because DNS resolution for 'backend:8000' failed. docker inspect showed empty networks {}.",
      "resolution": "Recreated nginx container with docker compose stop/rm/up, which properly attached it to trading_net"
    },
    {
      "issue": "Shark API SSL TLSV1_UNRECOGNIZED_NAME (pending verification)",
      "root_cause": "Likely missing or outdated CA certificates in the slim Python Docker image, or an incompatible TLS version negotiation with Shark Exchange's API server.",
      "resolution": "Added ca-certificates and openssl packages to runtime stage, added configurable SHARK_SSL_VERIFY setting (default true) that can be set to false as a workaround"
    }
  ],
  "deployment_verification": {
    "nginx_routes": {
      "/dashboard": {"status": "200", "size_bytes": 10931, "verified": true},
      "/api/v1/health": {"status": "pending_verification"}
    },
    "docker_network": {
      "nginx_on_trading_net": true,
      "all_services": ["postgres", "redis", "backend", "celery_worker", "celery_beat", "nginx", "frontend"]
    },
    "nextjs_build_args": {
      "docker-compose.yml": "NEXT_PUBLIC_API_BASE_URL=http://backend:8000 (via build.args)",
      "docker-compose.prod.yml": "NEXT_PUBLIC_API_BASE_URL=http://backend:8000 (via build.args)"
    }
  }
}
```

---

## Summary

| Domain | Status | Critical Issues | Warnings |
|--------|--------|-----------------|----------|
| **Frontend** | PARTIAL | 1 (no auth UI) | 2 (duplicate stores, duplicate interceptors) |
| **Backend** | PARTIAL | 1 (CORS localhost) | 2 (flush vs commit, tokenUrl) |
| **Database** | PASS | 0 | 0 |
| **Authentication** | PARTIAL | 1 (no frontend auth) | 1 (insecure SECRET_KEY default) |
| **Infrastructure** | PARTIAL | 1 (prod missing migrations) | 2 (nginx rate limit zone, redundant COPY) |

### Top 3 Actions Required

1. **Fix [`docker-compose.prod.yml:141`](docker-compose.prod.yml:141)** — Missing `PYTHONPATH=/app` and `alembic upgrade head` in production command
2. **Fix [`backend/app/main.py:93`](backend/app/main.py:93)** — CORS hardcoded to `localhost:3000`; won't work for EC2 public IP
3. **Create frontend auth pages** — No `/login` or `/signup` routes; users can't authenticate through the UI