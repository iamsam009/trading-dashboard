# 🏦 Trading Dashboard

Real-time trading dashboard with **FastAPI** backend and **Next.js** frontend.
Connects to the Shark trading platform for live orders, positions, P&L, and risk metrics.

---

## 📁 Project Structure

```
├── docker-compose.yml          # All services (postgres, redis, backend, celery, nginx, frontend)
├── .env.example                # Template for environment variables
├── generate_secret_key.py      # Script to generate a secure SECRET_KEY
├── backend/
│   ├── Dockerfile              # Python 3.11 slim image
│   ├── requirements.txt        # Python dependencies
│   └── app/
│       ├── __init__.py
│       ├── config.py           # Pydantic settings (reads .env)
│       └── main.py             # FastAPI app with /health, /ready endpoints
├── frontend/
│   ├── Dockerfile              # Node 20 alpine → Next.js standalone
│   └── package.json            # Next.js 14, TypeScript, Tailwind, Recharts, Lightweight Charts
├── nginx/
│   ├── nginx.conf              # Main Nginx configuration
│   └── conf.d/
│       └── default.conf        # Reverse proxy to backend (8000) & frontend (3000)
└── README.md
```

---

## ⚡ Quick Start

### Prerequisites

- **Docker** ≥ 24 & **Docker Compose** v2
- **pnpm** (for frontend development without Docker)

### 1. Clone & Configure

```bash
# Copy environment template
cp .env.example .env

# Generate a secure secret key
python generate_secret_key.py --write

# Edit .env and fill in your Shark API credentials:
#   SHARK_API_KEY=your_actual_key
#   SHARK_API_SECRET=your_actual_secret
```

### 2. Start Everything

```bash
docker compose up -d
```

First build may take a few minutes.  Once ready:

| Service          | URL                     |
|------------------|-------------------------|
| **Backend API**  | http://localhost:8000   |
| **Swagger Docs** | http://localhost:8000/docs (development only) |
| **Frontend**     | http://localhost:3000   |
| **Nginx (prod)** | http://localhost        |

### 3. Verify Health

```bash
curl http://localhost:8000/health   # → {"status":"ok"}
curl http://localhost:8000/ready    # → {"status":"ok","checks":{"database":true,"redis":true}}
```

---

## 🗄️ Database Migrations (Alembic)

Migrations are managed with Alembic.  Run inside the backend container:

```bash
# Generate a new migration after model changes
docker compose exec backend alembic revision --autogenerate -m "description"

# Apply pending migrations
docker compose exec backend alembic upgrade head
```

---

## 🔧 Environment Variables

| Variable                    | Default                                          | Description                           |
|-----------------------------|--------------------------------------------------|---------------------------------------|
| `POSTGRES_USER`             | `trading_user`                                   | PostgreSQL user                       |
| `POSTGRES_PASSWORD`         | `trading_pass`                                   | PostgreSQL password                   |
| `POSTGRES_DB`               | `trading_db`                                     | PostgreSQL database name              |
| `DATABASE_URL`              | `postgresql+asyncpg://…`                         | Full async DB connection string       |
| `REDIS_PASSWORD`            | `redis_pass`                                     | Redis AUTH password                   |
| `REDIS_URL`                 | `redis://:redis_pass@redis:6379/0`               | Redis connection string               |
| `SHARK_API_KEY`             | *(required)*                                     | Shark trading platform API key        |
| `SHARK_API_SECRET`          | *(required)*                                     | Shark trading platform API secret     |
| `SHARK_BASE_URL`            | `https://api.shark.in/v1`                        | Shark REST API base URL               |
| `SHARK_WS_URL`              | `wss://ws.shark.in/v1`                           | Shark WebSocket URL                   |
| `SECRET_KEY`                | *(generate with script)*                         | JWT signing key                       |
| `ALGORITHM`                 | `HS256`                                          | JWT algorithm                         |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `30`                                           | JWT access token TTL                  |
| `REFRESH_TOKEN_EXPIRE_DAYS` | `7`                                              | JWT refresh token TTL                 |
| `ENVIRONMENT`               | `production`                                     | `development` / `production`          |
| `LOG_LEVEL`                 | `info`                                           | Python logging level                  |
| `NEXT_PUBLIC_API_BASE_URL`  | `http://localhost:8000`                          | Frontend → backend API base           |
| `NEXT_PUBLIC_WS_URL`        | `ws://localhost:8000/ws`                         | Frontend → backend WebSocket          |

---

## 🐳 Docker Compose Services

| Service         | Image                | Port  | Description                      |
|-----------------|----------------------|-------|----------------------------------|
| `postgres`      | `postgres:16-alpine` | 5432  | Relational DB (persistent volume)|
| `redis`         | `redis:7-alpine`     | 6379  | Cache / Celery broker            |
| `backend`       | *built from source*  | 8000  | FastAPI REST + WebSocket server  |
| `celery_worker` | *built from source*  | —     | Async task processor             |
| `celery_beat`   | *built from source*  | —     | Periodic task scheduler          |
| `nginx`         | `nginx:1.25-alpine`  | 80    | Reverse proxy & static serving   |
| `frontend`      | *built from source*  | 3000  | Next.js frontend (standalone)    |

All services communicate over the `trading_net` Docker bridge network.

---

## 🛠️ Development Workflow

```bash
# Run only infrastructure
docker compose up -d postgres redis

# Backend (hot-reload via volume mount)
cd backend && pip install -r requirements.txt && uvicorn app.main:app --reload

# Frontend (hot-reload)
cd frontend && pnpm install && pnpm dev
```

---

## 📄 License

Proprietary – all rights reserved.