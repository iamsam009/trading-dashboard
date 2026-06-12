"""
Import all ORM models so Alembic's `env.py` can discover them via `Base.metadata`.

Order matters only for foreign-key resolution, but SQLAlchemy handles this
transparently as long as all models are imported before `Base.metadata.create_all`.
"""

from app.models.user import User
from app.models.api_key import APIKey
from app.models.strategy import Strategy
from app.models.trade import Trade
from app.models.position import Position
from app.models.risk_setting import RiskSetting
from app.models.log import Log
from app.models.performance import Performance

__all__ = [
    "User",
    "APIKey",
    "Strategy",
    "Trade",
    "Position",
    "RiskSetting",
    "Log",
    "Performance",
]