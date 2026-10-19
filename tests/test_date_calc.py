import asyncio
from datetime import date, datetime, timedelta, timezone

import pytest

import server


def freeze(monkeypatch, iso: str) -> None:
    """Pin server._now() to a fixed UTC instant."""
    fixed = datetime.fromisoformat(iso).replace(tzinfo=timezone.utc)
    monkeypatch.setattr(server, "_now", lambda: fixed)


def add(date: str, **kw) -> str:
    return server.date_calc("add", date, **kw)["result"]


@pytest.mark.parametrize(
    ("date", "months", "result", "clamped"),
    [("2026-01-31", 1, "2026-02-28", True),
     ("2024-01-31", 1, "2024-02-29", True),   # leap year
     ("2024-02-29", 12, "2025-02-28", True),  # leap day + 1 year
     ("2024-02-29", 48, "2028-02-29", False),
     ("2026-03-31", -1, "2026-02-28", True),
     ("2026-05-31", 1, "2026-06-30", True),
     ("2026-01-15", 1, "2026-02-15", False),
     ("2026-11-30", 3, "2027-02-28", True),   # across the year end
     ("2026-01-31", -13, "2024-12-31", False),
     ("1900-01-31", 1, "1900-02-28", True),   # 1900 is no leap year
     ("2000-01-31", 1, "2000-02-29", True)],  # 2000 is one
)
def test_add_months_clamps_month_end(date, months, result, clamped):
    r = server.date_calc("add", date, months=months)
    assert r["result"] == result
    assert r["month_end_clamped"] is clamped


def test_add_days_and_weeks():
    assert add("2026-12-31", days=1) == "2027-01-01"
    assert add("2024-02-28", days=1) == "2024-02-29"
    assert add("2026-02-28", days=1) == "2026-03-01"
    assert add("2026-03-01", days=-1) == "2026-02-28"
    assert add("2026-10-19", weeks=-2) == "2026-10-05"
    assert add("2026-10-19", days=0) == "2026-10-19"
    # DST change (Europe: 2026-03-29, 2026-10-25) has no effect on dates.
    assert add("2026-03-28", days=2) == "2026-03-30"
    assert add("2026-10-24", days=2) == "2026-10-26"


def test_add_months_then_weeks_and_days():
    r = server.date_calc("add", "2026-01-31", months=1, weeks=1, days=1)
    assert (r["result"], r["weekday"]) == ("2026-03-08", "Sunday")


def test_add_out_of_range():
    with pytest.raises(ValueError, match="9999-12-31"):
        server.date_calc("add", "9999-12-31", days=1)
    with pytest.raises(ValueError, match="0001-01-01"):
        server.date_calc("add", "0001-01-15", months=-1)


@pytest.mark.parametrize(
    ("start", "end", "days", "weeks", "wrest", "months", "mrest"),
    [("2026-01-01", "2026-12-31", 364, 52, 0, 11, 30),
     ("2024-01-01", "2025-01-01", 366, 52, 2, 12, 0),
     ("2026-01-31", "2026-02-28", 28, 4, 0, 1, 0),   # consistent with add + clamping
     ("2026-01-31", "2026-03-01", 29, 4, 1, 1, 1),
     ("2026-01-30", "2026-02-28", 29, 4, 1, 1, 0),   # 30 Jan + 1 month = 28 Feb
     ("2026-10-19", "2026-10-19", 0, 0, 0, 0, 0),
     ("2026-12-24", "2026-10-19", -66, -9, -3, -2, -5)],  # reversed: all negative
)
def test_diff(start, end, days, weeks, wrest, months, mrest):
    r = server.date_calc("diff", start, end_date=end)
    assert (r["days"], r["weeks"], r["weeks_remainder_days"]) == (days, weeks, wrest)
    assert (r["months"], r["months_remainder_days"]) == (months, mrest)


def test_diff_needs_end_date():
    with pytest.raises(ValueError, match="needs end_date"):
        server.date_calc("diff", "2026-10-19")


def test_info():
    assert server.date_calc("info", "2026-10-19") == {
        "date": "2026-10-19", "weekday": "Monday", "iso_week": 43, "iso_year": 2026,
        "day_of_year": 292, "days_in_month": 31, "is_leap_year": False, "is_workday": True,
    }


def test_info_iso_year_boundary_and_leap():
    r = server.date_calc("info", "2027-01-01")
    assert (r["iso_week"], r["iso_year"]) == (53, 2026)  # Friday of week 53/2026
    r = server.date_calc("info", "2024-12-30")
    assert (r["iso_week"], r["iso_year"]) == (1, 2025)
    r = server.date_calc("info", "2024-12-31")
    assert (r["day_of_year"], r["is_leap_year"]) == (366, True)
    assert server.date_calc("info", "2024-02-10")["days_in_month"] == 29


def test_info_with_state():
    r = server.date_calc("info", "2026-11-18", state="Sachsen")
    assert (r["state"], r["holiday"], r["is_workday"]) == ("SN", "Buß- und Bettag", False)
    r = server.date_calc("info", "2026-11-18", state="NW")
    assert (r["holiday"], r["is_workday"]) == (None, True)
    assert server.date_calc("info", "2026-10-18")["is_workday"] is False  # Sunday


@pytest.mark.parametrize(
    ("start", "end", "state", "count"),
    [("2026-10-19", "2026-10-23", None, 5),    # Mon-Fri, both inclusive
     ("2026-10-19", "2026-10-25", None, 5),
     ("2026-10-24", "2026-10-25", None, 0),    # weekend only
     ("2026-10-19", "2026-10-19", None, 1),
     ("2026-10-23", "2026-10-19", None, -5),   # reversed
     ("2026-01-01", "2026-12-31", None, 261),
     # NW: 11 holidays, 3 on a weekend (3 Oct, 1 Nov, 26 Dec)
     ("2026-01-01", "2026-12-31", "NW", 261 - 8),
     # BY: 13 holidays, 4 on a weekend (also 15 Aug)
     ("2026-01-01", "2026-12-31", "BY", 261 - 9),
     ("2026-11-16", "2026-11-20", "SN", 4),
     ("2026-11-16", "2026-11-20", "BY", 5),
     ("2026-03-30", "2026-04-10", "BE", 8)],   # Easter: Good Friday and Easter Monday
)
def test_workdays(start, end, state, count):
    assert server.date_calc("workdays", start, end_date=end, state=state)["workdays"] == count


def test_workdays_lists_excluded_holidays():
    r = server.date_calc("workdays", "2026-12-21", end_date="2027-01-08", state="BY")
    assert r["workdays"] == 12
    assert r["calendar_days"] == 19
    assert r["holidays_excluded_count"] == 3
    assert [h["date"] for h in r["holidays_excluded"]] == ["2026-12-25", "2027-01-01", "2027-01-06"]
    assert "holidays_excluded" not in server.date_calc("workdays", "2026-12-21", end_date="2027-01-08")


def test_workdays_match_day_by_day_count():
    # The weekly arithmetic must agree with counting day by day.
    holidays = {**server.holiday_dates(2026, "HH"), **server.holiday_dates(2027, "HH")}
    first = date(2026, 12, 14)
    for offset in range(14):
        start = first + timedelta(days=offset)
        for length in range(30):
            end = start + timedelta(days=length)
            expected = sum(
                d.weekday() < 5 and d not in holidays
                for d in (start + timedelta(days=i) for i in range(length + 1))
            )
            r = server.date_calc("workdays", start.isoformat(), end_date=end.isoformat(), state="HH")
            assert r["workdays"] == expected


@pytest.mark.parametrize(
    ("start", "n", "state", "result"),
    [("2026-10-23", 1, None, "2026-10-26"),    # Friday + 1 -> Monday
     ("2026-10-24", 1, None, "2026-10-26"),    # from Saturday
     ("2026-10-19", 5, None, "2026-10-26"),
     ("2026-10-26", -1, None, "2026-10-23"),
     ("2026-10-19", 0, None, "2026-10-19"),
     ("2026-12-23", 3, "NW", "2026-12-29"),    # skips 25 Dec
     ("2026-12-28", -3, "NW", "2026-12-22"),
     ("2026-04-02", 1, "NW", "2026-04-07"),    # Good Friday and Easter Monday
     ("2026-04-02", 1, None, "2026-04-03"),
     ("2026-11-17", 1, "SN", "2026-11-19")],
)
def test_add_workdays(start, n, state, result):
    assert server.date_calc("add_workdays", start, days=n, state=state)["result"] == result


def test_add_workdays_reports_skipped_holidays():
    r = server.date_calc("add_workdays", "2026-04-02", days=1, state="NW")
    assert [h["name"] for h in r["holidays_skipped"]] == ["Karfreitag", "Ostermontag"]
    assert r["weekday"] == "Tuesday"


def test_add_workdays_limit():
    with pytest.raises(ValueError, match="10000"):
        server.date_calc("add_workdays", "2026-10-19", days=10001)
    with pytest.raises(ValueError, match="1995"):
        server.date_calc("add_workdays", "2026-10-19", days=-9000, state="NW")


def test_today_uses_zone(monkeypatch):
    freeze(monkeypatch, "2026-10-18T23:30:00")  # Sunday in UTC, Monday in Berlin
    assert server.date_calc("info")["weekday"] == "Sunday"
    assert server.date_calc("info", timezone="Europe/Berlin")["date"] == "2026-10-19"
    monkeypatch.setattr(server, "DEFAULT_TZ", "Asia/Tokyo")
    assert server.date_calc("info", "TODAY")["date"] == "2026-10-19"
    r = server.date_calc("diff", "today", end_date="2026-12-24")
    assert r["days"] == 66


def test_weekday_language(monkeypatch):
    monkeypatch.setattr(server, "WEEKDAYS", server.WEEKDAY_NAMES["de"])
    assert server.date_calc("add", "2026-10-19", days=1)["weekday"] == "Dienstag"


@pytest.mark.parametrize("value", ["2026-02-29", "2026-13-01", "19.10.2026", "2026-W43-1", ""])
def test_invalid_dates(value):
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        server.date_calc("info", value)


def test_invalid_state_and_zone():
    with pytest.raises(ValueError, match="Unknown German state"):
        server.date_calc("workdays", "2026-10-19", end_date="2026-10-23", state="XX")
    with pytest.raises(ValueError, match="Europe/Berlin"):
        server.date_calc("info", timezone="Europe/Berln")


def test_operation_schema_is_enum():
    tool = next(t for t in asyncio.run(server.mcp.list_tools()) if t.name == "date_calc")
    assert tool.inputSchema["properties"]["operation"]["enum"] == [
        "add", "diff", "info", "workdays", "add_workdays",
    ]
    assert tool.inputSchema["required"] == ["operation"]
