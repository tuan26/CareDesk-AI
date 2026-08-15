"""One clock for the whole product.

Two different clocks were writing to the same columns. `server_default=func.now()`
is CURRENT_TIMESTAMP, which SQLite and Postgres both give in UTC; `datetime.now()`
gives whatever the machine is set to. On a Vietnamese laptop that is a seven-hour
gap inside a single table, so the inbox showed messages seven hours old the
moment they arrived — and, less visibly, every "hôm nay" report compared a UTC
column against a local range and silently counted the wrong day.

The fix is not "use UTC everywhere". This product is naive-local by design: a
working schedule is 08:00–17:00 at the clinic, a slot is 14:30 at the clinic, and
`date.today()` means today at the clinic. Introducing aware UTC datetimes on one
side of those comparisons would trade a visible seven-hour error for TypeErrors
and off-by-one days.

So: naive datetimes, always in clinic time. Explicitly Asia/Ho_Chi_Minh rather
than the machine's timezone, because production runs in UTC — `datetime.now()`
there is wrong for every clinic this is sold to, and wrong in a way nobody would
notice until a reminder went out at three in the morning.
"""
from datetime import date, datetime, timedelta, timezone

#: Vietnam has observed a single offset with no daylight saving since 1975, so a
#: fixed offset is accurate and needs no timezone database. Revisit only if the
#: product is sold outside ICT.
CLINIC_TZ = timezone(timedelta(hours=7), name="ICT")


def now() -> datetime:
    """Current clinic time, naive — comparable with everything already stored."""
    return datetime.now(CLINIC_TZ).replace(tzinfo=None)


def today() -> date:
    """Today at the clinic. At 04:00 UTC it is already tomorrow in Hanoi, and a
    server using its own date would offer a slot on a day that has passed."""
    return now().date()


def as_clinic_time(value: datetime) -> datetime:
    """Read a stored timestamp as clinic time.

    Rows written before this module existed carry UTC from CURRENT_TIMESTAMP.
    Aware values are converted; naive ones are already clinic time and returned
    untouched, so this is safe to apply to anything coming out of the database.
    """
    if value is None:
        return value
    return value.astimezone(CLINIC_TZ).replace(tzinfo=None) if value.tzinfo else value
