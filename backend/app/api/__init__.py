"""API v1 router – aggregates all sub-routers for the trading dashboard."""
from fastapi import APIRouter

from app.api.auth import router as auth_router
from app.api.api_keys import router as api_keys_router
from app.api.backtest import router as backtest_router
from app.api.dashboard import router as dashboard_router
from app.api.risk import router as risk_router
from app.api.strategies import router as strategies_router
from app.api.trading import router as trading_router
from app.api.ws_endpoints import router as ws_router

router = APIRouter(prefix="/api/v1")

router.include_router(auth_router, prefix="/auth", tags=["Authentication"])
router.include_router(api_keys_router, prefix="/api-keys", tags=["API Keys"])
router.include_router(backtest_router, prefix="/backtest", tags=["Backtesting"])
router.include_router(dashboard_router, prefix="/dashboard", tags=["Dashboard"])
router.include_router(risk_router, prefix="/risk", tags=["Risk Management"])
router.include_router(strategies_router, prefix="/strategies", tags=["Strategies"])
router.include_router(trading_router, prefix="/trading", tags=["Trading"])
router.include_router(ws_router, prefix="/ws", tags=["WebSocket"])