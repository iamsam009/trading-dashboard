"""
Technical Analysis indicators implemented with plain Python (numpy optional).

All functions accept ``np.ndarray`` or plain ``list[float]`` values and return
the same type.  Performance-sensitive paths should use numpy arrays.

Supported indicators
--------------------
- SMA    – Simple Moving Average
- EMA    – Exponential Moving Average
- RSI    – Relative Strength Index
- MACD   – Moving Average Convergence Divergence (line, signal, histogram)
- BB     – Bollinger Bands (upper, middle, lower)
- ATR    – Average True Range
- VOLUME – (pass-through – volume data comes from the feed)
- VWAP   – Volume-Weighted Average Price
"""

from __future__ import annotations

import math
from typing import Sequence, TypeVar

###############################################################################
# Optional numpy import – graceful fallback to pure-Python math
###############################################################################
try:
    import numpy as np

    _HAS_NUMPY = True
except ImportError:  # pragma: no cover
    np = None  # type: ignore[assignment]
    _HAS_NUMPY = False

_T = TypeVar("_T", list[float], "np.ndarray")  # type: ignore[name-defined]


# ── Helpers ────────────────────────────────────────────────────────────────
def _to_seq(values: Sequence[float] | None) -> Sequence[float]:
    """Normalize inputs to a sequence (list or ndarray)."""
    if values is None:
        return []
    return values


# ── SMA ────────────────────────────────────────────────────────────────────
def sma(values: Sequence[float], period: int) -> _T:
    """Simple Moving Average.

    Args:
        values: Price series (close prices by default).
        period: Lookback window length.

    Returns:
        SMA series; first ``period-1`` entries are ``NaN``.
    """
    values = _to_seq(values)
    if _HAS_NUMPY and isinstance(values, np.ndarray):
        result = np.full(len(values), np.nan)
        if len(values) >= period:
            result[period - 1 :] = np.convolve(values, np.ones(period) / period, mode="valid")  # noqa: E501
        return result  # type: ignore[return-value]

    # Pure-Python fallback
    result: list[float] = [float("nan")] * len(values)
    if len(values) >= period:
        window_sum = sum(values[:period])
        result[period - 1] = window_sum / period
        for i in range(period, len(values)):
            window_sum += values[i] - values[i - period]
            result[i] = window_sum / period
    return result  # type: ignore[return-value]


# ── EMA ────────────────────────────────────────────────────────────────────
def ema(values: Sequence[float], period: int) -> _T:
    """Exponential Moving Average.

    Uses Wilder's smoothing: ``alpha = 1 / period``, seeded with the SMA
    of the first ``period`` values.
    """
    values = _to_seq(values)
    alpha = 2.0 / (period + 1)

    if _HAS_NUMPY and isinstance(values, np.ndarray):
        result = np.full(len(values), np.nan)
        if len(values) < period:
            return result  # type: ignore[return-value]
        result[period - 1] = np.mean(values[:period])
        for i in range(period, len(values)):
            result[i] = (values[i] - result[i - 1]) * alpha + result[i - 1]
        return result  # type: ignore[return-value]

    result: list[float] = [float("nan")] * len(values)
    if len(values) < period:
        return result  # type: ignore[return-value]
    result[period - 1] = sum(values[:period]) / period
    for i in range(period, len(values)):
        result[i] = (values[i] - result[i - 1]) * alpha + result[i - 1]
    return result  # type: ignore[return-value]


# ── RSI ────────────────────────────────────────────────────────────────────
def rsi(values: Sequence[float], period: int = 14) -> _T:
    """Relative Strength Index (Wilder's smoothing).

    Returns:
        RSI series; first ``period`` entries are ``NaN``.
    """
    values = _to_seq(values)
    if len(values) <= period:
        if _HAS_NUMPY and isinstance(values, np.ndarray):
            return np.full(len(values), np.nan)  # type: ignore[return-value]
        return [float("nan")] * len(values)  # type: ignore[return-value]

    deltas = [values[i] - values[i - 1] for i in range(1, len(values))]

    if _HAS_NUMPY and isinstance(values, np.ndarray):
        deltas_arr = np.array(deltas)
        gains = np.where(deltas_arr > 0, deltas_arr, 0.0)
        losses = np.where(deltas_arr < 0, -deltas_arr, 0.0)

        result = np.full(len(values), np.nan)
        avg_gain = np.mean(gains[:period])
        avg_loss = np.mean(losses[:period])

        if avg_loss == 0:
            result[period] = 100.0
        else:
            rs = avg_gain / avg_loss
            result[period] = 100.0 - (100.0 / (1.0 + rs))

        for i in range(period + 1, len(values)):
            avg_gain = (avg_gain * (period - 1) + gains[i - 1]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i - 1]) / period
            if avg_loss == 0:
                result[i] = 100.0
            else:
                rs = avg_gain / avg_loss
                result[i] = 100.0 - (100.0 / (1.0 + rs))
        return result  # type: ignore[return-value]

    # Pure-Python fallback
    gains = [max(d, 0) for d in deltas]
    losses = [max(-d, 0) for d in deltas]

    result: list[float] = [float("nan")] * len(values)

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    if avg_loss == 0:
        result[period] = 100.0
    else:
        result[period] = 100.0 - (100.0 / (1.0 + avg_gain / avg_loss))

    for i in range(period + 1, len(values)):
        avg_gain = (avg_gain * (period - 1) + gains[i - 1]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i - 1]) / period
        if avg_loss == 0:
            result[i] = 100.0
        else:
            result[i] = 100.0 - (100.0 / (1.0 + avg_gain / avg_loss))

    return result  # type: ignore[return-value]


# ── MACD ───────────────────────────────────────────────────────────────────
def macd(
    values: Sequence[float],
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> tuple[_T, _T, _T]:
    """Moving Average Convergence Divergence.

    Returns:
        (macd_line, signal_line, histogram) as three series of the same length.
        ``histogram = macd_line - signal_line``.
    """
    values = _to_seq(values)
    ema_fast = ema(values, fast)
    ema_slow = ema(values, slow)

    if _HAS_NUMPY and isinstance(values, np.ndarray):
        macd_line = ema_fast - ema_slow  # type: ignore[operator]
        signal_line = ema(macd_line, signal)  # type: ignore[arg-type]
        histogram = macd_line - signal_line  # type: ignore[operator]
        return macd_line, signal_line, histogram  # type: ignore[return-value]

    # Pure-Python
    macd_line: list[float] = [
        (f - s if not (math.isnan(f) or math.isnan(s)) else float("nan"))
        for f, s in zip(ema_fast, ema_slow)
    ]
    signal_line = ema(macd_line, signal)
    histogram = [
        (m - s if not (math.isnan(m) or math.isnan(s)) else float("nan"))
        for m, s in zip(macd_line, signal_line)
    ]
    return macd_line, signal_line, histogram  # type: ignore[return-value]


# ── Bollinger Bands ────────────────────────────────────────────────────────
def bollinger_bands(
    values: Sequence[float],
    period: int = 20,
    num_std: float = 2.0,
) -> tuple[_T, _T, _T]:
    """Bollinger Bands.

    Returns:
        (upper, middle, lower) – middle is SMA(period), bands are ±num_std
        standard deviations from the middle.
    """
    values = _to_seq(values)
    middle = sma(values, period)

    if _HAS_NUMPY and isinstance(values, np.ndarray):
        result_upper = np.full(len(values), np.nan)
        result_lower = np.full(len(values), np.nan)
        if len(values) >= period:
            # Rolling std
            rolling_std = np.array(
                [np.nanstd(values[i - period + 1 : i + 1]) for i in range(period - 1, len(values))]
            )
            result_upper[period - 1 :] = middle[period - 1 :] + num_std * rolling_std  # type: ignore[index]
            result_lower[period - 1 :] = middle[period - 1 :] - num_std * rolling_std  # type: ignore[index]
        return result_upper, middle, result_lower  # type: ignore[return-value]

    # Pure-Python
    upper: list[float] = [float("nan")] * len(values)
    lower: list[float] = [float("nan")] * len(values)
    for i in range(period - 1, len(values)):
        window = values[i - period + 1 : i + 1]
        mean = sum(window) / period
        variance = sum((x - mean) ** 2 for x in window) / period
        std = math.sqrt(variance)
        upper[i] = mean + num_std * std
        lower[i] = mean - num_std * std
    return upper, middle, lower  # type: ignore[return-value]


# ── ATR ────────────────────────────────────────────────────────────────────
def atr(
    high: Sequence[float],
    low: Sequence[float],
    close: Sequence[float],
    period: int = 14,
) -> _T:
    """Average True Range (Wilder's smoothing)."""
    high = _to_seq(high)
    low = _to_seq(low)
    close = _to_seq(close)
    length = min(len(high), len(low), len(close))

    if length < 2:
        if _HAS_NUMPY and isinstance(high, np.ndarray):
            return np.full(len(high), np.nan)  # type: ignore[return-value]
        return [float("nan")] * len(high)  # type: ignore[return-value]

    # Compute True Range
    tr: list[float] = [float("nan")]
    for i in range(1, length):
        h_l = high[i] - low[i]
        h_pc = abs(high[i] - close[i - 1])
        l_pc = abs(low[i] - close[i - 1])
        tr.append(max(h_l, h_pc, l_pc))

    if _HAS_NUMPY and isinstance(high, np.ndarray):
        tr_arr = np.array(tr)
        result = np.full(len(high), np.nan)
        if length > period:
            result[period] = np.mean(tr_arr[1 : period + 1])
            for i in range(period + 1, length):
                result[i] = (result[i - 1] * (period - 1) + tr_arr[i]) / period
        return result  # type: ignore[return-value]

    result: list[float] = [float("nan")] * len(high)
    if length > period:
        result[period] = sum(tr[1 : period + 1]) / period
        for i in range(period + 1, length):
            result[i] = (result[i - 1] * (period - 1) + tr[i]) / period
    return result  # type: ignore[return-value]


# ── VWAP ───────────────────────────────────────────────────────────────────
def vwap(
    high: Sequence[float],
    low: Sequence[float],
    close: Sequence[float],
    volume: Sequence[float],
) -> _T:
    """Volume-Weighted Average Price (cumulative, resets daily).

    Uses typical price ``(H + L + C) / 3`` weighted by volume.
    """
    high = _to_seq(high)
    low = _to_seq(low)
    close = _to_seq(close)
    volume = _to_seq(volume)
    length = min(len(high), len(low), len(close), len(volume))

    if _HAS_NUMPY and isinstance(high, np.ndarray):
        result = np.full(len(high), np.nan)
        cum_pv = 0.0
        cum_vol = 0.0
        for i in range(length):
            typical = (high[i] + low[i] + close[i]) / 3.0
            cum_pv += typical * volume[i]
            cum_vol += volume[i]
            result[i] = cum_pv / cum_vol if cum_vol > 0 else float("nan")
        return result  # type: ignore[return-value]

    result: list[float] = [float("nan")] * len(high)
    cum_pv = 0.0
    cum_vol = 0.0
    for i in range(length):
        typical = (high[i] + low[i] + close[i]) / 3.0
        cum_pv += typical * volume[i]
        cum_vol += volume[i]
        result[i] = cum_pv / cum_vol if cum_vol > 0 else float("nan")
    return result  # type: ignore[return-value]


# ── Indicator registry (for dynamic dispatch) ──────────────────────────────
_INDICATOR_REGISTRY: dict[str, object] = {
    "SMA": sma,
    "EMA": ema,
    "RSI": rsi,
    "MACD": macd,
    "MACD_SIGNAL": lambda v, f, s, sig: macd(v, f, s, sig)[1],
    "MACD_HIST": lambda v, f, s, sig: macd(v, f, s, sig)[2],
    "BB_UPPER": lambda v, p, std: bollinger_bands(v, p, std)[0],
    "BB_MIDDLE": lambda v, p, std: bollinger_bands(v, p, std)[1],
    "BB_LOWER": lambda v, p, std: bollinger_bands(v, p, std)[2],
    "ATR": atr,
    "VWAP": vwap,
}