"""Auto-brightness control based on time of day.

Schedule (with 30-minute linear transitions at each boundary):
  07:00 – 19:00 → 80%
  19:00 – 22:00 → 50%
  22:00 – 07:00 → 20%
"""

from __future__ import annotations

from datetime import datetime

from loguru import logger as log

# (hour_as_float, brightness_pct) knots — closed loop
_KNOTS: list[tuple[float, int]] = [
    (7.0,  80),
    (19.0, 80),
    (19.5, 50),   # 30-min ramp 80→50
    (22.0, 50),
    (22.5, 20),   # 30-min ramp 50→20
    (31.0, 20),   # 07:00 next day = 24+7
    (31.5, 80),   # 30-min ramp 20→80
]


def _time_to_float(h: int, m: int) -> float:
    """Convert hour/minute to fractional hours, adjusted so night spans 22–31."""
    t = h + m / 60.0
    # Shift early-morning hours (0–7:30) past midnight into the next day slot
    if t < 7.5:
        t += 24.0
    return t


def get_brightness_for_time(now: datetime | None = None) -> int:
    """Return deck brightness (0-100) for the current (or given) time."""
    if now is None:
        now = datetime.now()
    t = _time_to_float(now.hour, now.minute)

    # Find surrounding knots
    for i in range(len(_KNOTS) - 1):
        t0, b0 = _KNOTS[i]
        t1, b1 = _KNOTS[i + 1]
        if t0 <= t <= t1:
            if t1 == t0:
                return b0
            alpha = (t - t0) / (t1 - t0)
            return round(b0 + alpha * (b1 - b0))

    # Fallback (should not happen)
    return 80


def apply_auto_brightness(deck_controller) -> None:
    """Read current time and set deck brightness accordingly."""
    try:
        pct = get_brightness_for_time()
        deck_controller.deck.set_brightness(pct)
        log.debug(f"Auto-brightness applied: {pct}%")
    except Exception as e:
        log.warning(f"Auto-brightness failed: {e}")
