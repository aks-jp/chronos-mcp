from datetime import date, datetime, timezone

import pytest

import server


def freeze(monkeypatch, iso: str) -> None:
    """Pin server._now() to a fixed UTC instant."""
    fixed = datetime.fromisoformat(iso).replace(tzinfo=timezone.utc)
    monkeypatch.setattr(server, "_now", lambda: fixed)


def names(year: int, state: str) -> dict[str, str]:
    return {h["name"]: h["date"] for h in server.holidays(year, state)["holidays"]}


@pytest.mark.parametrize(
    ("year", "easter"),
    [(2000, "2000-04-23"), (2008, "2008-03-23"), (2011, "2011-04-24"),
     (2019, "2019-04-21"), (2024, "2024-03-31"), (2025, "2025-04-20"),
     (2026, "2026-04-05"), (2027, "2027-03-28"), (2038, "2038-04-25"),
     (2285, "2285-03-22")],  # 2285 and 2038: earliest and latest possible dates
)
def test_easter_sunday(year, easter):
    assert server.easter_sunday(year).isoformat() == easter


def test_movable_feasts_2026():
    h = names(2026, "NW")
    assert h["Karfreitag"] == "2026-04-03"
    assert h["Ostermontag"] == "2026-04-06"
    assert h["Christi Himmelfahrt"] == "2026-05-14"
    assert h["Pfingstmontag"] == "2026-05-25"
    assert h["Fronleichnam"] == "2026-06-04"


@pytest.mark.parametrize(
    ("year", "day"),
    [(2023, "2023-11-22"), (2024, "2024-11-20"), (2025, "2025-11-19"),
     (2026, "2026-11-18"), (2027, "2027-11-17"), (2030, "2030-11-20")],
)
def test_repentance_day_saxony(year, day):
    assert names(year, "SN")["Buß- und Bettag"] == day
    assert "Buß- und Bettag" not in names(year, "BY")


@pytest.mark.parametrize(
    ("state", "count"),
    [("BW", 12), ("BY", 13), ("BE", 10), ("BB", 12), ("HB", 10), ("HH", 10),
     ("HE", 10), ("MV", 11), ("NI", 10), ("NW", 11), ("RP", 11), ("SL", 12),
     ("SN", 11), ("ST", 11), ("SH", 10), ("TH", 11)],
)
def test_counts_per_state_2026(state, count):
    r = server.holidays(2026, state)
    assert r["count"] == count == len(r["holidays"])
    nationwide = [h["name"] for h in r["holidays"] if h["nationwide"]]
    assert len(nationwide) == 9
    dates = [h["date"] for h in r["holidays"]]
    assert dates == sorted(dates)


@pytest.mark.parametrize(
    ("name", "states"),
    [("Heilige Drei Könige", {"BW", "BY", "ST"}),
     ("Fronleichnam", {"BW", "BY", "HE", "NW", "RP", "SL"}),
     ("Mariä Himmelfahrt", {"BY", "SL"}),
     ("Allerheiligen", {"BW", "BY", "NW", "RP", "SL"}),
     ("Reformationstag", {"BB", "HB", "HH", "MV", "NI", "SN", "ST", "SH", "TH"}),
     ("Internationaler Frauentag", {"BE", "MV"}),
     ("Weltkindertag", {"TH"}),
     ("Ostersonntag", {"BB"}),
     ("Pfingstsonntag", {"BB"})],
)
def test_state_specific_holidays_2026(name, states):
    assert {s for s in server.STATES if name in names(2026, s)} == states


def test_introduction_years():
    assert "Internationaler Frauentag" not in names(2018, "BE")
    assert names(2019, "BE")["Internationaler Frauentag"] == "2019-03-08"
    assert "Internationaler Frauentag" not in names(2022, "MV")
    assert names(2023, "MV")["Internationaler Frauentag"] == "2023-03-08"
    assert "Weltkindertag" not in names(2018, "TH")
    assert names(2019, "TH")["Weltkindertag"] == "2019-09-20"
    assert "Reformationstag" not in names(2016, "NI")
    assert names(2018, "NI")["Reformationstag"] == "2018-10-31"
    assert names(2016, "SN")["Reformationstag"] == "2016-10-31"


def test_reformation_day_2017_nationwide():
    for state in server.STATES:
        entry = next(h for h in server.holidays(2017, state)["holidays"]
                     if h["name"] == "Reformationstag")
        assert entry["nationwide"] is True
    assert "Reformationstag" not in names(2016, "BY")


@pytest.mark.parametrize(
    ("year", "name", "day"),
    [(2020, "Tag der Befreiung", "2020-05-08"),
     (2025, "Tag der Befreiung", "2025-05-08"),
     (2028, "75. Jahrestag des Volksaufstands in der DDR", "2028-06-17")],
)
def test_berlin_one_offs(year, name, day):
    assert names(year, "BE")[name] == day
    assert name not in names(year + 1, "BE")
    assert name not in names(year, "BB")


def test_notes():
    r = server.holidays(2026, "BY")
    assumption = next(h for h in r["holidays"] if h["name"] == "Mariä Himmelfahrt")
    assert "municipalities" in assumption["note"]
    saarland = next(h for h in server.holidays(2026, "SL")["holidays"]
                    if h["name"] == "Mariä Himmelfahrt")
    assert "note" not in saarland
    assert "Augsburg" in r["notes"][0]
    assert "notes" not in server.holidays(2026, "NW")


@pytest.mark.parametrize(
    ("alias", "code"),
    [("nrw", "NW"), ("Bayern", "BY"), ("Bavaria", "BY"), ("Thüringen", "TH"),
     ("thueringen", "TH"), ("Baden-Württemberg", "BW"), ("DE-SN", "SN"),
     (" mecklenburg-vorpommern ", "MV"), ("Lower Saxony", "NI"), ("hh", "HH")],
)
def test_state_aliases(alias, code):
    assert server.resolve_state(alias) == code


def test_unknown_state_suggests_correction():
    with pytest.raises(ValueError, match="Did you mean: BY"):
        server.resolve_state("Bayrn")
    with pytest.raises(ValueError, match="Use a code"):
        server.resolve_state("Texas")


def test_year_range():
    with pytest.raises(ValueError, match="1995"):
        server.holidays(1994, "NW")
    with pytest.raises(ValueError, match="2100"):
        server.holidays(2101, "NW")


def test_default_state_and_year(monkeypatch):
    freeze(monkeypatch, "2026-12-31T23:30:00")  # already 2027 in Berlin
    monkeypatch.setattr(server, "DEFAULT_STATE", "BY")
    r = server.holidays()
    assert (r["year"], r["state"], r["state_name"]) == (2026, "BY", "Bayern")
    assert server.holidays(timezone="Europe/Berlin")["year"] == 2027


def test_check_single_date(monkeypatch):
    r = server.holidays(state="SN", date="2026-11-18")
    assert r == {"date": "2026-11-18", "weekday": "Wednesday", "state": "SN",
                 "state_name": "Sachsen", "is_holiday": True,
                 "holiday": "Buß- und Bettag"}
    assert server.holidays(state="NW", date="2026-11-18")["is_holiday"] is False
    freeze(monkeypatch, "2026-10-03T10:00:00")
    assert server.holidays(date="today")["holiday"] == "Tag der Deutschen Einheit"


def test_weekday_follows_language(monkeypatch):
    monkeypatch.setattr(server, "WEEKDAYS", server.WEEKDAY_NAMES["de"])
    first = server.holidays(2026, "NW")["holidays"][0]
    assert first == {"date": "2026-01-01", "weekday": "Donnerstag",
                     "name": "Neujahr", "nationwide": True}


@pytest.mark.parametrize("value", ["2026-02-30", "19.10.2026", "20261019", "tomorrow"])
def test_invalid_date(value):
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        server.holidays(date=value)


def test_all_years_compute():
    first, last = server.HOLIDAY_YEARS
    for year in range(first, last + 1):
        for state in server.STATES:
            days = [date.fromisoformat(h["date"]) for h in server.holidays(year, state)["holidays"]]
            assert all(d.year == year for d in days)
            assert 9 <= len(days) <= 14


def test_two_holidays_on_one_day():
    # 2008: Ascension Day fell on 1 May.
    r = server.holidays(state="NW", date="2008-05-01")
    assert r["holiday"] == "Tag der Arbeit / Christi Himmelfahrt"
    assert server.holiday_dates(2008, "NW")[date(2008, 5, 1)] == r["holiday"]


ALL_SAINTS_STATES = {"BW", "BY", "NW", "RP", "SL"}


def codes(entries: list[dict]) -> set[str]:
    return {e["state"] for e in entries}


@pytest.mark.parametrize("alias", ["all", "ALL", "alle", "Alle", "DE", "de", "Deutschland"])
def test_all_states_aliases(alias):
    r = server.holidays(state=alias, date="2026-11-01")
    assert r["state"] == "all"
    assert len(r["states"]) == 16


def test_all_states_all_saints_2026():
    r = server.holidays(state="all", date="2026-11-01")
    assert (r["date"], r["weekday"]) == ("2026-11-01", "Sunday")
    assert codes(r["holiday_in"]) == ALL_SAINTS_STATES
    assert codes(r["not_holiday_in"]) == set(server.STATES) - ALL_SAINTS_STATES
    assert (r["holiday_in_count"], r["not_holiday_in_count"]) == (5, 11)
    assert r["is_holiday_nationwide"] is False
    assert {"state": "RP", "state_name": "Rheinland-Pfalz"} in r["holiday_in"]
    assert {"state": "HE", "state_name": "Hessen"} in r["not_holiday_in"]
    per_state = {s["state"]: s for s in r["states"]}
    assert list(per_state) == list(server.STATES)
    for code, entry in per_state.items():
        assert entry["state_name"] == server.STATES[code]
        assert entry["is_holiday"] is (code in ALL_SAINTS_STATES)
        assert entry["holiday"] == ("Allerheiligen" if code in ALL_SAINTS_STATES else None)


def test_all_states_matches_single_state_answers():
    r = server.holidays(state="all", date="2026-11-01")
    for entry in r["states"]:
        single = server.holidays(state=entry["state"], date="2026-11-01")
        assert (single["is_holiday"], single["holiday"]) == (entry["is_holiday"], entry["holiday"])


def test_all_states_reformation_day_2026():
    r = server.holidays(state="all", date="2026-10-31")
    expected = {"BB", "HB", "HH", "MV", "NI", "SN", "ST", "SH", "TH"}
    assert codes(r["holiday_in"]) == expected
    assert codes(r["not_holiday_in"]) == set(server.STATES) - expected
    assert {s["holiday"] for s in r["states"] if s["is_holiday"]} == {"Reformationstag"}


def test_all_states_nationwide_day():
    r = server.holidays(state="all", date="2026-10-03")
    assert r["is_holiday_nationwide"] is True
    assert r["holiday_in_count"] == 16 and r["not_holiday_in"] == []
    assert {s["holiday"] for s in r["states"]} == {"Tag der Deutschen Einheit"}


def test_all_states_ordinary_day():
    r = server.holidays(state="all", date="2026-11-02")
    assert r["holiday_in"] == [] and r["not_holiday_in_count"] == 16


def test_all_states_today(monkeypatch):
    freeze(monkeypatch, "2026-10-31T23:30:00")  # already 1 November in Berlin
    assert server.holidays(state="all", date="today")["date"] == "2026-10-31"
    r = server.holidays(state="all", date="today", timezone="Europe/Berlin")
    assert r["date"] == "2026-11-01" and r["holiday_in_count"] == 5


def test_all_states_year_listing():
    r = server.holidays(2026, "all")
    assert (r["year"], r["state"]) == (2026, "all")
    assert r["nationwide_count"] == len(r["nationwide"]) == 9
    assert [h["name"] for h in r["nationwide"]][:2] == ["Neujahr", "Karfreitag"]
    assert all("nationwide" not in h for h in r["nationwide"])
    assert list(r["states"]) == list(server.STATES)
    for code, entry in r["states"].items():
        single = server.holidays(2026, code)
        assert entry["state_name"] == server.STATES[code]
        assert entry["count"] == single["count"] == 9 + len(entry["additional"])
        assert [h["name"] for h in entry["additional"]] == \
            [h["name"] for h in single["holidays"] if not h["nationwide"]]
        assert entry.get("notes") == single.get("notes")
    by = [h["name"] for h in r["states"]["BY"]["additional"]]
    assert by == ["Heilige Drei Könige", "Fronleichnam", "Mariä Himmelfahrt", "Allerheiligen"]
    assert "note" in r["states"]["BY"]["additional"][2]
    assert r["states"]["HE"]["additional"] == [
        {"date": "2026-06-04", "weekday": "Thursday", "name": "Fronleichnam"}]


def test_all_states_year_2017_reformation_nationwide():
    r = server.holidays(2017, "all")
    assert "Reformationstag" in [h["name"] for h in r["nationwide"]]
    assert all("Reformationstag" not in [h["name"] for h in e["additional"]]
               for e in r["states"].values())


def test_all_states_default_year_and_range(monkeypatch):
    freeze(monkeypatch, "2026-12-31T23:30:00")
    assert server.holidays(state="all")["year"] == 2026
    assert server.holidays(state="all", timezone="Europe/Berlin")["year"] == 2027
    with pytest.raises(ValueError, match="1995"):
        server.holidays(1994, "all")


def test_all_states_year_listing_stays_small():
    import json
    assert len(json.dumps(server.holidays(2026, "all"), ensure_ascii=False)) < 6000


def test_single_state_unchanged_by_all_mode():
    # "DE-NW" is still one state, not "all".
    assert server.holidays(state="DE-NW", date="2026-11-01")["state"] == "NW"
