"""MongoDB (via motor, by default) stores and returns naive UTC datetimes --
mixing those with timezone-aware datetimes raises TypeError on comparison.
Everything in this codebase stores and compares naive UTC datetimes via
utcnow(); to_utc() normalizes any tz-aware datetime read from elsewhere
(e.g. an external API response) down to the same naive-UTC convention.
"""

from datetime import datetime, timezone


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def to_utc_naive(dt: datetime) -> datetime:
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt
