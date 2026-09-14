import pytest

from tools import parse_nas, t100_kpis


def rows(code, months, pax, seats, deps=100, intl=10, dist=500.0):
    """One T-100 row per month with constant values (strings, as Socrata returns them)."""
    return [
        {"origin_airport_code": code, "reporting_month": f"{m}-01T00:00:00.000",
         "total_departures": str(deps), "total_passengers": str(pax), "total_seats": str(seats),
         "outbound_international": str(intl), "total_distance_flight_sm": str(dist),
         "origin_airport_name": f"Test ({code})"}
        for m in months
    ]


def months(start_year, end_year, end_month=12):
    out = []
    for y in range(start_year, end_year + 1):
        for m in range(1, 13):
            if y == end_year and m > end_month:
                break
            out.append(f"{y}-{m:02d}")
    return out


def test_windows_and_growth_with_partial_latest_year():
    # 2019-01 .. 2026-04: last full year 2025, trailing 12 = 2025-05..2026-04, prior = 2024-05..2025-04
    ms = months(2019, 2026, 4)
    r = [
        # pax 1000/month in 2019, 2000/month from 2020 on: CAGR 2019->2025 = 2^(1/6)-1
        *[dict(x, total_passengers="1000" if m.startswith("2019") else "2000")
          for x, m in zip(rows("AAA", ms, 0, 2500), ms)],
    ]
    k = t100_kpis(r)
    assert k["latest_month"] == "2026-04"
    assert k["growth_window"] == "2019-2025"
    assert k["trailing_12_months"] == "2025-05 to 2026-04"
    a = k["airports"]["AAA"]
    assert a["pax_growth"] == pytest.approx(2 ** (1 / 6) - 1, abs=1e-4)
    assert a["load_factor"] == pytest.approx(2000 / 2500, abs=1e-4)
    assert a["seat_growth"] == 0.0  # constant seats
    assert a["scale"] == 12 * 2000
    assert a["intl_share"] == pytest.approx(10 / 100, abs=1e-4)
    assert a["avg_stage_mi"] == 500
    assert a["months_in_window"] == 12


def test_december_latest_month_uses_that_year_as_last_full_year():
    k = t100_kpis(rows("AAA", months(2019, 2025), 100, 200))
    assert k["growth_window"] == "2019-2025"
    assert k["airports"]["AAA"]["pax_growth"] == 0.0


def test_seat_growth_compares_trailing_12_to_prior_12():
    ms = months(2024, 2025)
    r = [dict(x, total_seats="100" if m.startswith("2024") else "110") for x, m in zip(rows("AAA", ms, 50, 0), ms)]
    assert t100_kpis(r)["airports"]["AAA"]["seat_growth"] == pytest.approx(0.10, abs=1e-4)


def test_missing_base_year_gives_null_growth_not_crash():
    k = t100_kpis(rows("AAA", months(2023, 2025), 100, 200))
    assert k["airports"]["AAA"]["pax_growth"] is None
    assert k["airports"]["AAA"]["load_factor"] == 0.5


def test_multiple_airports_are_split():
    r = rows("AAA", months(2025, 2025), 100, 200) + rows("BBB", months(2025, 2025), 300, 400)
    k = t100_kpis(r)
    assert set(k["airports"]) == {"AAA", "BBB"}
    assert k["airports"]["BBB"]["scale"] == 3600


def test_empty_rows():
    assert t100_kpis([]) == {}


NAS_XML = """<AIRPORT_STATUS_INFORMATION><Update_Time>Sun Sep 13 13:58:40 2026 GMT</Update_Time>
<Delay_type><Name>Ground Stop Programs</Name><Ground_Stop_List><Program><ARPT>EWR</ARPT><Reason>WX</Reason><End_Time>15:00</End_Time></Program></Ground_Stop_List></Delay_type>
<Delay_type><Name>Ground Delay Programs</Name><Ground_Delay_List><Ground_Delay><ARPT>BOS</ARPT><Reason>runway construction</Reason><Avg>2 hours</Avg><Max>3 hours</Max></Ground_Delay></Ground_Delay_List></Delay_type>
<Delay_type><Name>Airport Closures</Name><Airport_Closure_List><Airport><ARPT>LAX</ARPT><Reason>GA only NOTAM</Reason><Start>May 27</Start><Reopen>May 28</Reopen></Airport></Airport_Closure_List></Delay_type>
</AIRPORT_STATUS_INFORMATION>"""


def test_parse_nas_events():
    update, events = parse_nas(NAS_XML)
    assert update.startswith("Sun Sep 13")
    by = {e["code"]: e for e in events}
    assert by["EWR"]["type"] == "Ground Stop Programs" and by["EWR"]["end"] == "15:00"
    assert by["BOS"]["avg_delay"] == "2 hours" and by["BOS"]["max_delay"] == "3 hours"
    assert by["LAX"]["start"] == "May 27" and by["LAX"]["end"] == "May 28"


def test_severity_mapping():
    from tools import severity
    assert severity("Ground Stop Programs") == 2
    assert severity("Ground Delay Programs") == 1
    assert severity("Airport Closures") == 1


def test_cargo_context_fields():
    # 1,000 pax/month, 50 of them international; 12 months of freight+mail; all 10 intl departures are freighters
    r = rows("CGO", months(2025, 2025), 1000, 2000)
    for x in r:
        x["outbound_international_1"] = "50"
        x["total_freight_lbs"] = "1000000"
        x["total_mail_lbs"] = "500"
    a = t100_kpis(r)["airports"]["CGO"]
    assert a["intl_pax_share"] == 0.05
    assert a["freight_lbs"] == 12 * 1000500
    assert a["intl_share"] == 0.1  # departure-based share still includes the freighters


def test_missing_cargo_fields_default_to_zero():
    a = t100_kpis(rows("AAA", months(2025, 2025), 100, 200))["airports"]["AAA"]
    assert a["intl_pax_share"] == 0.0 and a["freight_lbs"] == 0


def test_domestic_only_rows_lack_intl_field():
    r = rows("AAA", months(2025, 2025), 100, 200)
    for x in r:
        del x["outbound_international"]
    a = t100_kpis(r)["airports"]["AAA"]
    assert a["intl_share"] == 0.0 and a["load_factor"] == 0.5
