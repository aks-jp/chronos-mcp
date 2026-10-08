import difflib
import os
from datetime import datetime, timezone as dt_tz
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


@mcp.custom_route("/health", methods=["GET"])
async def health(_: Request) -> JSONResponse:
    return JSONResponse({"status": "ok",
                         "utc": _now().isoformat(timespec="seconds")})


if __name__ == "__main__":
    mcp.run(transport=TRANSPORT)
