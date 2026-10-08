import asyncio
from datetime import datetime, timezone

import pytest

import server


def freeze(monkeypatch, iso: str) -> None:
    """Pin server._now() to a fixed UTC instant."""
    fixed = datetime.fromisoformat(iso).replace(tzinfo=timezone.utc)
    monkeypatch.setattr(server, "_now", lambda: fixed)


@pytest.mark.parametrize(
    ("utc", "local", "abbr", "offset", "dst"),
    [
        # Spring forward 2026-03-29: 01:00 UTC is the switch instant.
        ("2026-03-29T00:59:00", "01:59:00", "CET", "+01:00", False),
        ("2026-03-29T01:00:00", "03:00:00", "CEST", "+02:00", True),
        # Fall back 2026-10-25: 01:00 UTC is the switch instant.
        ("2026-10-25T00:59:00", "02:59:00", "CEST", "+02:00", True),
        ("2026-10-25T01:00:00", "02:00:00", "CET", "+01:00", False),
    ],
)
def test_dst_transitions_berlin(monkeypatch, utc, local, abbr, offset, dst):
    freeze(monkeypatch, utc)
    r = server.get_current_time("Europe/Berlin")
    assert r["time"] == local
    assert r["abbreviation"] == abbr
    assert r["utc_offset"] == offset
    assert r["is_dst"] is dst


@pytest.mark.parametrize(
    ("zone", "offset", "time"),
    [("Asia/Kolkata", "+05:30", "17:30:00"), ("Asia/Kathmandu", "+05:45", "17:45:00")],
)
def test_fractional_offsets(monkeypatch, zone, offset, time):
    freeze(monkeypatch, "2026-10-08T12:00:00")
    r = server.get_current_time(zone)
    assert r["utc_offset"] == offset
    assert r["time"] == time


def test_date_line_day_change():
    r = server.convert_time("2026-10-08T10:00", "Pacific/Pago_Pago", ["Pacific/Kiritimati"])
    target = r["targets"][0]
    assert r["source"]["utc_offset"] == "-11:00"
    assert target["utc_offset"] == "+14:00"
    assert target["iso"] == "2026-10-09T11:00:00+14:00"
    assert target["day_change"] == 1
    assert target["hours_vs_source"] == 25.0


def test_convert_hh_mm_uses_today_in_source_zone(monkeypatch):
    freeze(monkeypatch, "2026-10-08T23:30:00")  # already 2026-10-09 in Berlin
    r = server.convert_time("09:00", "Europe/Berlin", ["America/New_York"])
    assert r["source"]["iso"] == "2026-10-09T09:00:00+02:00"
    assert r["targets"][0]["iso"] == "2026-10-09T03:00:00-04:00"
    assert r["targets"][0]["hours_vs_source"] == -6.0


def test_unknown_zone_suggests_correction():
    with pytest.raises(ValueError, match="Europe/Berlin"):
        server.resolve("Europe/Berln")


@pytest.mark.parametrize(
    ("alias", "zone"),
    [("MEZ", "Europe/Berlin"), ("nyc", "America/New_York"), (" Tokyo ", "Asia/Tokyo")],
)
def test_aliases(alias, zone):
    assert str(server.resolve(alias)) == zone


def test_multiple_zones_share_instant(monkeypatch):
    freeze(monkeypatch, "2026-10-08T12:32:05")
    r = server.get_current_time(["Europe/Berlin", "Asia/Tokyo", "America/New_York"])
    assert len({x["unix"] for x in r["results"]}) == 1
    assert r["results"][0]["unix"] == 1791462725


def test_zone_limit(monkeypatch):
    freeze(monkeypatch, "2026-10-08T12:00:00")
    r = server.get_current_time(["UTC"] * 15)
    assert len(r["results"]) == 10


def test_default_zone(monkeypatch):
    freeze(monkeypatch, "2026-10-08T12:00:00")
    monkeypatch.setattr(server, "DEFAULT_TZ", "Asia/Tokyo")
    assert server.get_current_time()["timezone"] == "Asia/Tokyo"


def test_example_fields(monkeypatch):
    freeze(monkeypatch, "2026-10-08T12:32:05")
    monkeypatch.setattr(server, "WEEKDAYS", server.WEEKDAY_NAMES["de"])
    assert server.get_current_time("Europe/Berlin") == {
        "timezone": "Europe/Berlin",
        "iso": "2026-10-08T14:32:05+02:00",
        "date": "2026-10-08",
        "time": "14:32:05",
        "weekday": "Donnerstag",
        "utc_offset": "+02:00",
        "abbreviation": "CEST",
        "is_dst": True,
        "iso_week": 41,
        "unix": 1791462725,
    }


def test_weekday_default_english(monkeypatch):
    freeze(monkeypatch, "2026-10-08T12:00:00")
    assert server.get_current_time("UTC")["weekday"] == "Thursday"


def test_list_timezones():
    r = server.list_timezones("tokyo")
    assert r["timezones"] == ["Asia/Tokyo"]
    full = server.list_timezones()
    assert full["count"] > 50
    assert len(full["timezones"]) == 50


def test_tools_are_marked_read_only():
    tools = asyncio.run(server.mcp.list_tools())
    assert {t.name for t in tools} == {"get_current_time", "convert_time", "list_timezones"}
    for tool in tools:
        assert tool.annotations.readOnlyHint is True
        assert tool.annotations.destructiveHint is False
        assert tool.annotations.openWorldHint is False
