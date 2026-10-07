"""熬锅出胶门槛（两条同时满足才放行）：

1. 最近一次煮胶峰值温度 ≥ 90℃；
2. 至少一条未作废的比重读数落在 1.02–1.08（含）。
"""

from app.models import GravityReading, Kettle

MIN_PEAK = 90.0
MIN_GRAVITY = 1.02
MAX_GRAVITY = 1.08


class RuleError(ValueError):
    pass


def latest_peak(kettle: Kettle) -> float | None:
    if not kettle.cooks:
        return None
    latest = max(kettle.cooks, key=lambda c: c.taken_at)
    return latest.peak_temp_c


def active_readings(kettle: Kettle) -> list[GravityReading]:
    return [r for r in (kettle.gravity_readings or []) if r.voided_at is None]


def gravity_in_band(value: float) -> bool:
    return MIN_GRAVITY <= value <= MAX_GRAVITY


def qualifying_gravity(kettle: Kettle) -> GravityReading | None:
    """返回一条可放行的比重读数：未作废且在 1.02–1.08（含）。"""
    for reading in active_readings(kettle):
        if gravity_in_band(reading.gravity):
            return reading
    return None


def assert_can_set_status(kettle: Kettle, new_status: str) -> None:
    allowed = {Kettle.STATUS_COLD, Kettle.STATUS_BOILING, Kettle.STATUS_DRAWN}
    if new_status not in allowed:
        raise RuleError(f"无效状态：{new_status}")
    if new_status != Kettle.STATUS_DRAWN:
        return
    peak = latest_peak(kettle)
    if peak is None:
        raise RuleError("该锅尚无煮胶峰值，不能出胶")
    if peak < MIN_PEAK:
        raise RuleError(f"最近峰值 {peak}℃ 低于 {MIN_PEAK:.0f}℃，不能出胶")
    if qualifying_gravity(kettle) is None:
        raise RuleError(
            f"缺少未作废且比重在 {MIN_GRAVITY:.2f}–{MAX_GRAVITY:.2f} 的读数，不能出胶"
        )
