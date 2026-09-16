"""Calendar bounds shared by period-based workflow queries."""
import re
from datetime import datetime


def period_bounds(period: str):
    """Return inclusive start and exclusive end for a year, quarter or month."""
    value = period.strip()
    if value == "CURRENT":
        value = datetime.now().strftime("%Y-%m")
    match = re.fullmatch(r"(\d{4})(?:-(?:(\d{2})|Q([1-4])))?", value)
    if not match:
        raise ValueError("Period must be YYYY-MM, YYYY-Q1 through YYYY-Q4, or YYYY.")
    year = int(match[1])
    month = int(match[2]) if match[2] else (int(match[3]) - 1) * 3 + 1 if match[3] else 1
    width = 1 if match[2] else 3 if match[3] else 12
    start = datetime(year, month, 1)
    end_month = month + width
    end = datetime(year + (end_month - 1) // 12, (end_month - 1) % 12 + 1, 1)
    return start, end


def ledger_period_filter(period_column, date_column, period):
    """Match fiscal period labels and dated rows inside the selected period."""
    from sqlalchemy import and_, or_
    start, end = period_bounds(period)
    value = period.strip()
    months = []
    quarters = set()
    current = start
    while current < end:
        months.append(current.strftime("%Y-%m"))
        quarters.add(f"{current.year:04d}-Q{((current.month - 1) // 3) + 1}")
        current = datetime(current.year + current.month // 12, current.month % 12 + 1, 1)
    labels = [value, *months, *sorted(quarters)]
    if len(months) == 12:
        labels.append(start.strftime("%Y"))
    return or_(
        period_column.in_(labels),
        and_(date_column >= start, date_column < end),
    )
