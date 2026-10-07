"""熬锅出胶门槛：最近峰值 ≥ 90℃，且须有未作废、比重落在 1.02–1.08（含）的读数。"""

from app.models import DensityReading, Kettle

MIN_PEAK = 90.0
SG_MIN = 1.02
SG_MAX = 1.08


class RuleError(ValueError):
    pass


def latest_peak(kettle: Kettle) -> float | None:
    if not kettle.cooks:
        return None
    latest = max(kettle.cooks, key=lambda c: c.taken_at)
    return latest.peak_temp_c


def is_qualified(reading: DensityReading) -> bool:
    """未作废且比重落在 [1.02, 1.08] 的读数才算合格，可用于放行出胶。"""
    return reading.voided_at is None and SG_MIN <= reading.gravity <= SG_MAX


def qualified_readings(kettle: Kettle) -> list[DensityReading]:
    return [r for r in (kettle.readings or []) if is_qualified(r)]


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
    if not qualified_readings(kettle):
        raise RuleError(
            f"该锅尚无合格比重读数（未作废且比重在 {SG_MIN:.2f}–{SG_MAX:.2f} 之间），不能出胶"
        )
