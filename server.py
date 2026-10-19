import calendar
import difflib
import os
import re
from datetime import date as dt_date, datetime, timedelta, timezone as dt_tz
from functools import lru_cache
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from starlette.requests import Request
from starlette.responses import JSONResponse

DEFAULT_TZ = os.getenv("DEFAULT_TIMEZONE", "UTC")
TRANSPORT = os.getenv("MCP_TRANSPORT", "streamable-http")  # or "stdio"
WEEKDAY_LANG = os.getenv("WEEKDAY_LANG", "en").strip().lower()
ALL_ZONES = sorted(available_timezones())
ALIASES = {
    "MEZ": "Europe/Berlin", "MESZ": "Europe/Berlin", "CET": "Europe/Berlin",
    "BERLIN": "Europe/Berlin", "LONDON": "Europe/London", "NYC": "America/New_York",
    "TOKYO": "Asia/Tokyo", "GMT": "UTC", "Z": "UTC",
}
WEEKDAY_NAMES = {
    "en": ["Monday", "Tuesday", "Wednesday", "Thursday",
           "Friday", "Saturday", "Sunday"],
    "de": ["Montag", "Dienstag", "Mittwoch", "Donnerstag",
           "Freitag", "Samstag", "Sonntag"],
}
if WEEKDAY_LANG not in WEEKDAY_NAMES:
    raise SystemExit(
        f"Unsupported WEEKDAY_LANG '{WEEKDAY_LANG}', use one of: {', '.join(WEEKDAY_NAMES)}"
    )
WEEKDAYS = WEEKDAY_NAMES[WEEKDAY_LANG]

# German states (ISO 3166-2:DE codes without the "DE-" prefix).
STATES = {
    "BW": "Baden-Württemberg", "BY": "Bayern", "BE": "Berlin", "BB": "Brandenburg",
    "HB": "Bremen", "HH": "Hamburg", "HE": "Hessen", "MV": "Mecklenburg-Vorpommern",
    "NI": "Niedersachsen", "NW": "Nordrhein-Westfalen", "RP": "Rheinland-Pfalz",
    "SL": "Saarland", "SN": "Sachsen", "ST": "Sachsen-Anhalt",
    "SH": "Schleswig-Holstein", "TH": "Thüringen",
}
# Keys are normalised by _norm_state(): lower case, umlauts spelled out, no punctuation.
STATE_ALIASES = {
    "bawue": "BW", "badenwurttemberg": "BW", "bavaria": "BY", "hesse": "HE",
    "mecklenburgwesternpomerania": "MV", "mecklenburgwestpomerania": "MV",
    "lowersaxony": "NI", "nds": "NI", "nrw": "NW", "northrhinewestphalia": "NW",
    "rlp": "RP", "rhinelandpalatinate": "RP", "saxony": "SN",
    "saxonyanhalt": "ST", "lsa": "ST", "thuringia": "TH", "thuringen": "TH",
}
HOLIDAY_YEARS = (1995, 2100)  # current rules; Buß- und Bettag was nationwide until 1994
MAX_WORKDAYS = 10000
OUT_OF_RANGE = "Result is outside the supported range 0001-01-01 to 9999-12-31."


def _norm_state(name: str) -> str:
    s = name.strip().lower()
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        s = s.replace(a, b)
    return re.sub(r"[^a-z]", "", s)


STATE_KEYS = {
    **{_norm_state(code): code for code in STATES},
    **{_norm_state(name): code for code, name in STATES.items()},
    **STATE_ALIASES,
}


def resolve_state(name: str) -> str:
    key = _norm_state(name)
    if len(key) == 4 and key.startswith("de") and key[2:].upper() in STATES:
        key = key[2:]  # "DE-NW"
    if key in STATE_KEYS:
        return STATE_KEYS[key]
    hints = {STATE_KEYS[k] for k in difflib.get_close_matches(key, STATE_KEYS, n=3, cutoff=0.6)}
    raise ValueError(
        f"Unknown German state '{name}'. "
        + (f"Did you mean: {', '.join(sorted(hints))}? " if hints else "")
        + f"Use a code ({', '.join(STATES)}) or a name like 'Bayern' or 'NRW'."
    )


try:
    DEFAULT_STATE = resolve_state(os.getenv("DEFAULT_STATE", "NW"))
except ValueError as e:
    raise SystemExit(f"Invalid DEFAULT_STATE: {e}")

mcp = FastMCP(
    "chronos-mcp",
    host=os.getenv("MCP_HOST", "0.0.0.0"),
    port=int(os.getenv("MCP_PORT", "8765")),
    stateless_http=True,
)

# All tools only read the clock and the bundled timezone database.
READ_ONLY = ToolAnnotations(
    readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False
)


def _now() -> datetime:
    """Current time in UTC; patched in tests."""
    return datetime.now(dt_tz.utc)


def resolve(name: str) -> ZoneInfo:
    key = ALIASES.get(name.strip().upper(), name.strip())
    try:
        return ZoneInfo(key)
    except (ZoneInfoNotFoundError, ValueError):
        hints = difflib.get_close_matches(key, ALL_ZONES, n=5, cutoff=0.5)
        raise ValueError(
            f"Unknown timezone '{name}'. "
            f"Did you mean: {', '.join(hints) or 'use list_timezones'}?"
        )


def describe(dt: datetime) -> dict:
    z = dt.strftime("%z")
    return {
        "timezone": str(dt.tzinfo),
        "iso": dt.isoformat(timespec="seconds"),
        "date": dt.date().isoformat(),
        "time": dt.strftime("%H:%M:%S"),
        "weekday": WEEKDAYS[dt.weekday()],
        "utc_offset": f"{z[:3]}:{z[3:]}",
        "abbreviation": dt.tzname(),
        "is_dst": bool(dt.dst()),
        "iso_week": dt.isocalendar().week,
        "unix": int(dt.timestamp()),
    }


def parse_date(value: str, timezone: str | None = None) -> dt_date:
    """'YYYY-MM-DD' or 'today' (in the given zone or the server zone)."""
    v = value.strip()
    if v.lower() == "today":
        return _now().astimezone(resolve(timezone or DEFAULT_TZ)).date()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
        raise ValueError(f"Invalid date '{value}'. Use YYYY-MM-DD (e.g. '2026-10-19') or 'today'.")
    try:
        return dt_date.fromisoformat(v)
    except ValueError as e:
        raise ValueError(f"Invalid date '{value}': {e}. Use YYYY-MM-DD or 'today'.")


def easter_sunday(year: int) -> dt_date:
    """Gregorian Easter Sunday (anonymous Gregorian / Meeus-Jones-Butcher algorithm)."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(h + l - 7 * m + 114, 31)
    return dt_date(year, month, day + 1)


# Statutory public holidays per the state holiday laws (Feiertagsgesetze),
# checked against de.wikipedia.org/wiki/Gesetzliche_Feiertage_in_Deutschland
# (October 2026):
# - Ostersonntag/Pfingstsonntag are listed only in Brandenburg (FTG BB § 2);
#   Hesse protects them as ordinary Sundays (HFeiertagsG § 1).
# - Frauentag: BE since 2019, MV since 2023. Weltkindertag: TH since 2019.
# - Reformationstag: BB, MV, SN, ST, TH since 1990; HB, HH, NI, SH since 2018;
#   nationwide once in 2017 (500th anniversary).
# - Buß- und Bettag: nationwide until 1994, since 1995 only SN.
# - One-offs in BE: 8 May 2020 and 2025 (75th/80th anniversary of the end of
#   WW II), 17 June 2028 (75th anniversary of the 1953 uprising in the GDR).
# Each rule: (name, date function, applies(year, state), note or None).
def _fixed(month: int, day: int):
    return lambda y, easter: dt_date(y, month, day)


def _easter(offset: int):
    return lambda y, easter: easter + timedelta(days=offset)


def _states(*codes: str, since: int = 0):
    return lambda y, s: s in codes and y >= since


def _everywhere(y: int, s: str) -> bool:
    return True


def _reformation_day(y: int, s: str) -> bool:
    return (y == 2017 or s in ("BB", "MV", "SN", "ST", "TH")
            or (s in ("HB", "HH", "NI", "SH") and y >= 2018))


def _repentance_day(y: int, easter: dt_date) -> dt_date:
    nov22 = dt_date(y, 11, 22)  # Wednesday before 23 November
    return nov22 - timedelta(days=(nov22.weekday() - 2) % 7)


HOLIDAY_RULES = [
    ("Neujahr", _fixed(1, 1), _everywhere, None),
    ("Heilige Drei Könige", _fixed(1, 6), _states("BW", "BY", "ST"), None),
    ("Internationaler Frauentag", _fixed(3, 8),
     lambda y, s: (s == "BE" and y >= 2019) or (s == "MV" and y >= 2023), None),
    ("Karfreitag", _easter(-2), _everywhere, None),
    ("Ostersonntag", _easter(0), _states("BB"), "Sunday; statutory holiday only in Brandenburg"),
    ("Ostermontag", _easter(1), _everywhere, None),
    ("Tag der Arbeit", _fixed(5, 1), _everywhere, None),
    ("Tag der Befreiung", _fixed(5, 8), lambda y, s: s == "BE" and y in (2020, 2025),
     "One-off holiday in Berlin (75th/80th anniversary of the end of World War II)"),
    ("Christi Himmelfahrt", _easter(39), _everywhere, None),
    ("Pfingstsonntag", _easter(49), _states("BB"), "Sunday; statutory holiday only in Brandenburg"),
    ("Pfingstmontag", _easter(50), _everywhere, None),
    ("Fronleichnam", _easter(60), _states("BW", "BY", "HE", "NW", "RP", "SL"), None),
    ("75. Jahrestag des Volksaufstands in der DDR", _fixed(6, 17),
     lambda y, s: s == "BE" and y == 2028, "One-off holiday in Berlin"),
    ("Mariä Himmelfahrt", _fixed(8, 15), _states("BY", "SL"), None),
    ("Weltkindertag", _fixed(9, 20), _states("TH", since=2019), None),
    ("Tag der Deutschen Einheit", _fixed(10, 3), _everywhere, None),
    ("Reformationstag", _fixed(10, 31), _reformation_day, None),
    ("Allerheiligen", _fixed(11, 1), _states("BW", "BY", "NW", "RP", "SL"), None),
    ("Buß- und Bettag", _repentance_day, _states("SN"), None),
    ("1. Weihnachtstag", _fixed(12, 25), _everywhere, None),
    ("2. Weihnachtstag", _fixed(12, 26), _everywhere, None),
]
HOLIDAY_NOTES = {
    ("BY", "Mariä Himmelfahrt"): "Only in municipalities with a predominantly Catholic "
    "population (about 1,700 of 2,056); counted as a holiday here",
}
STATE_NOTES = {
    "BY": ["Augsburger Hohes Friedensfest (8 August) is a holiday only in the city of Augsburg; not included"],
    "SN": ["Fronleichnam is a holiday only in some Catholic municipalities of the Sorbian area; not included"],
    "TH": ["Fronleichnam is a holiday only in some Catholic municipalities (e.g. Eichsfeld); not included"],
}


@lru_cache(maxsize=512)
def holiday_list(year: int, state: str) -> tuple[tuple[dt_date, str, bool, str | None], ...]:
    """(date, name, nationwide, note) for one year and state code, sorted by date."""
    if not HOLIDAY_YEARS[0] <= year <= HOLIDAY_YEARS[1]:
        raise ValueError(
            f"Year {year} is out of range; public holidays are available for "
            f"{HOLIDAY_YEARS[0]}–{HOLIDAY_YEARS[1]}."
        )
    easter = easter_sunday(year)
    days = []
    for name, when, applies, note in HOLIDAY_RULES:
        if applies(year, state):
            nationwide = all(applies(year, s) for s in STATES)
            days.append((when(year, easter), name, nationwide,
                         HOLIDAY_NOTES.get((state, name), note)))
    return tuple(sorted(days, key=lambda h: h[0]))


def holiday_dates(year: int, state: str) -> dict[dt_date, str]:
    """Date -> name; two holidays on one day (e.g. 1 May 2008) are joined with ' / '."""
    days: dict[dt_date, str] = {}
    for d, name, _, _ in holiday_list(year, state):
        days[d] = f"{days[d]} / {name}" if d in days else name
    return days


def add_months(day: dt_date, months: int) -> tuple[dt_date, bool]:
    """Add calendar months; a day past the target month's end is clamped to it."""
    y, m = divmod(day.month - 1 + months, 12)
    year, month = day.year + y, m + 1
    if not 1 <= year <= 9999:
        raise OverflowError
    last = calendar.monthrange(year, month)[1]
    return dt_date(year, month, min(day.day, last)), day.day > last


def month_diff(start: dt_date, end: dt_date) -> tuple[int, int]:
    """Full calendar months from start to end (start <= end) and the remaining days."""
    months = (end.year - start.year) * 12 + end.month - start.month
    if add_months(start, months)[0] > end:
        months -= 1
    return months, (end - add_months(start, months)[0]).days


def _holidays_in(start: dt_date, end: dt_date, state: str | None) -> dict[dt_date, str]:
    """Holidays of the state between start and end (inclusive) that fall on Mon-Fri."""
    if state is None:
        return {}
    days = {}
    for year in range(start.year, end.year + 1):
        days.update(holiday_dates(year, state))
    return {d: n for d, n in sorted(days.items()) if start <= d <= end and d.weekday() < 5}


def _day_list(days: dict[dt_date, str]) -> list[dict]:
    return [{"date": d.isoformat(), "weekday": WEEKDAYS[d.weekday()], "name": n}
            for d, n in list(days.items())[:50]]


@mcp.tool(annotations=READ_ONLY)
def get_current_time(timezone: str | list[str] | None = None) -> dict:
    """Get the current date and time. Pass one IANA timezone
    (e.g. 'Europe/Berlin') or a list of up to 10. Defaults to the server zone."""
    zones = [timezone] if isinstance(timezone, str) else (timezone or [DEFAULT_TZ])
    now = _now()
    results = [describe(now.astimezone(resolve(z))) for z in zones[:10]]
    return results[0] if len(results) == 1 else {"results": results}


@mcp.tool(annotations=READ_ONLY)
def convert_time(time: str, source_timezone: str, target_timezones: list[str]) -> dict:
    """Convert a time between timezones. 'time' is 'HH:MM' (today in the
    source zone) or an ISO datetime like '2026-12-24T18:00'."""
    src = resolve(source_timezone)
    if len(time) <= 5 and ":" in time:
        h, m = map(int, time.split(":"))
        dt = _now().astimezone(src).replace(hour=h, minute=m, second=0, microsecond=0)
    else:
        dt = datetime.fromisoformat(time)
        dt = dt.replace(tzinfo=src) if dt.tzinfo is None else dt.astimezone(src)
    targets = []
    for name in target_timezones[:10]:
        t = dt.astimezone(resolve(name))
        r = describe(t)
        r["hours_vs_source"] = (t.utcoffset() - dt.utcoffset()).total_seconds() / 3600
        r["day_change"] = (t.date() - dt.date()).days
        targets.append(r)
    return {"source": describe(dt), "targets": targets}


@mcp.tool(annotations=READ_ONLY)
def list_timezones(filter: str = "") -> dict:
    """List valid IANA timezone names, optionally filtered by a substring
    such as 'Europe' or 'Tokyo'. Returns at most 50 names."""
    hits = [z for z in ALL_ZONES if filter.lower() in z.lower()]
    return {"count": len(hits), "timezones": hits[:50]}


@mcp.tool(annotations=READ_ONLY)
def holidays(year: int | None = None, state: str | None = None,
             date: str | None = None, timezone: str | None = None) -> dict:
    """Statutory public holidays in Germany for a year (default: this year)
    and a state (code like 'NW', 'BY' or a name like 'Bayern'; defaults to the
    server state). Pass 'date' (YYYY-MM-DD or 'today') to check one day instead."""
    code = resolve_state(state) if state else DEFAULT_STATE
    if date is not None:
        day = parse_date(date, timezone)
        name = holiday_dates(day.year, code).get(day)
        return {
            "date": day.isoformat(), "weekday": WEEKDAYS[day.weekday()],
            "state": code, "state_name": STATES[code],
            "is_holiday": name is not None, "holiday": name,
        }
    if year is None:
        year = parse_date("today", timezone).year
    days = []
    for d, name, nationwide, note in holiday_list(year, code):
        entry = {"date": d.isoformat(), "weekday": WEEKDAYS[d.weekday()],
                 "name": name, "nationwide": nationwide}
        if note:
            entry["note"] = note
        days.append(entry)
    result = {"year": year, "state": code, "state_name": STATES[code],
              "count": len(days), "holidays": days}
    if code in STATE_NOTES:
        result["notes"] = STATE_NOTES[code]
    return result


@mcp.tool(annotations=READ_ONLY)
def date_calc(
    operation: Literal["add", "diff", "info", "workdays", "add_workdays"],
    date: str = "today",
    end_date: str | None = None,
    days: int = 0,
    weeks: int = 0,
    months: int = 0,
    state: str | None = None,
    timezone: str | None = None,
) -> dict:
    """Calendar math on dates ('YYYY-MM-DD' or 'today').
    add: date + months, weeks, days (negative subtracts; 31 Jan + 1 month = end of Feb).
    diff: date to end_date in days, weeks and calendar months.
    info: weekday, ISO week, day of year, leap year.
    workdays: Mon-Fri from date to end_date, both inclusive.
    add_workdays: date + 'days' working days (negative goes back).
    Optional 'state' (German state like 'NW') also skips its public holidays."""
    start = parse_date(date, timezone)
    code = resolve_state(state) if state else None
    if operation in ("diff", "workdays"):
        if end_date is None:
            raise ValueError(f"Operation '{operation}' needs end_date (YYYY-MM-DD or 'today').")
        end = parse_date(end_date, timezone)
        lo, hi, sign = (start, end, 1) if start <= end else (end, start, -1)
    if operation == "add":
        try:
            result, clamped = add_months(start, months)
            result += timedelta(weeks=weeks, days=days)
        except OverflowError:
            raise ValueError(OUT_OF_RANGE)
        return {"date": start.isoformat(), "result": result.isoformat(),
                "weekday": WEEKDAYS[result.weekday()], "month_end_clamped": clamped}

    if operation == "diff":
        total = (hi - lo).days
        m, m_rest = month_diff(lo, hi)
        return {
            "date": start.isoformat(), "end_date": end.isoformat(),
            "days": sign * total,
            "weeks": sign * (total // 7), "weeks_remainder_days": sign * (total % 7),
            "months": sign * m, "months_remainder_days": sign * m_rest,
        }

    if operation == "info":
        r = {
            "date": start.isoformat(), "weekday": WEEKDAYS[start.weekday()],
            "iso_week": start.isocalendar().week, "iso_year": start.isocalendar().year,
            "day_of_year": start.timetuple().tm_yday,
            "days_in_month": calendar.monthrange(start.year, start.month)[1],
            "is_leap_year": calendar.isleap(start.year),
        }
        is_workday = start.weekday() < 5
        if code:
            name = holiday_dates(start.year, code).get(start)
            r.update(state=code, holiday=name)
            is_workday = is_workday and name is None
        r["is_workday"] = is_workday
        return r

    if operation == "workdays":
        total = (hi - lo).days + 1
        full_weeks, rest = divmod(total, 7)
        count = full_weeks * 5 + sum((lo.weekday() + i) % 7 < 5 for i in range(rest))
        excluded = _holidays_in(lo, hi, code)
        r = {"date": start.isoformat(), "end_date": end.isoformat(),
             "workdays": sign * (count - len(excluded)), "calendar_days": total}
        if code:
            r.update(state=code, holidays_excluded_count=len(excluded),
                     holidays_excluded=_day_list(excluded))
        return r

    # add_workdays
    if abs(days) > MAX_WORKDAYS:
        raise ValueError(f"At most {MAX_WORKDAYS} working days per call; split larger steps.")
    step, left, day, skipped = (1 if days >= 0 else -1), abs(days), start, {}
    try:
        while left:
            day += timedelta(days=step)
            name = holiday_dates(day.year, code).get(day) if code else None
            if day.weekday() < 5 and name:
                skipped[day] = name
            elif day.weekday() < 5:
                left -= 1
    except OverflowError:
        raise ValueError(OUT_OF_RANGE)
    r = {"date": start.isoformat(), "workdays_added": days, "result": day.isoformat(),
         "weekday": WEEKDAYS[day.weekday()]}
    if code:
        r.update(state=code, holidays_skipped=_day_list(skipped))
    return r


@mcp.custom_route("/health", methods=["GET"])
async def health(_: Request) -> JSONResponse:
    return JSONResponse({"status": "ok",
                         "utc": _now().isoformat(timespec="seconds")})


if __name__ == "__main__":
    mcp.run(transport=TRANSPORT)
