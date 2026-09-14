"""Live data tools: BTS T-100 (Socrata) and FAA NAS status. No cache, no snapshots, plain Python.

Aviation terms used here
------------------------
BTS T-100   The US Bureau of Transportation Statistics form T-100: every airline reports, per
            month and per route, how many flights it operated and how many seats and passengers
            it carried. We use the "by origin airport" summary (one row per airport per month).
Socrata     The open-data API that data.bts.gov runs on; queried with SoQL ($select, $where).
FAA NAS     The Federal Aviation Administration's National Airspace System status feed: which
            airports have an active delay program right now, and why.
Ground stop         The FAA holds flights bound for an airport on the ground at their origin.
                    The most severe live delay signal (severity 2 here).
Ground delay program (GDP)  Flights bound for an airport are metered with assigned delays,
                    usually for weather, runway work or volume (severity 1).
NOTAM       Notice to Air Missions: a formal notice about a facility condition, for example a
            closure. Many closure NOTAMs concern general-aviation (private, non-airline) use only.
Load factor Passengers / seats flown. Stage length: the average flight distance in statute miles.
CAGR        Compound annual growth rate between two years.
"""

import xml.etree.ElementTree as ET
from collections import defaultdict

import httpx

T100_URL = "https://data.bts.gov/resource/r495-tyji.json"
NAS_URL = "https://nasstatus.faa.gov/api/airport-status-information"
T100_FIELDS = (
    "origin_airport_code,reporting_month,total_departures,total_passengers,total_seats,"
    "outbound_international,outbound_international_1,total_freight_lbs,total_mail_lbs,"
    "total_distance_flight_sm,origin_airport_name"
)  # outbound_international_1 is the dataset's name for international passengers
BASE_YEAR = 2019  # pre-COVID anchor for growth
TIMEOUT = 30


# ---- BTS T-100 -----------------------------------------------------------------------------

def _num(v):
    """Socrata returns numbers as strings and omits nulls; treat missing as 0 for sums."""
    return float(v) if v not in (None, "") else 0.0


def t100_kpis(rows: list[dict]) -> dict:
    """Aggregate raw T-100 rows (one per airport-month) into per-airport KPIs.

    Growth is CAGR from BASE_YEAR to the latest full calendar year; load factor, seat growth,
    scale and intl share use the trailing 12 months ending at the latest reporting month.
    """
    if not rows:
        return {}
    months = sorted({r["reporting_month"][:7] for r in rows})
    latest = months[-1]
    latest_year = int(latest[:4])
    last_full_year = latest_year if latest.endswith("-12") else latest_year - 1
    t12 = months[-12:]  # trailing 12 months
    p12 = months[-24:-12]  # the 12 before them

    by_code: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_code[r["origin_airport_code"]].append(r)

    out = {}
    for code, rs in by_code.items():
        def total(field, sel):
            return sum(_num(r.get(field)) for r in rs if sel(r["reporting_month"][:7]))

        pax_base = total("total_passengers", lambda m: m.startswith(str(BASE_YEAR)))
        pax_last = total("total_passengers", lambda m: m.startswith(str(last_full_year)))
        years = last_full_year - BASE_YEAR
        pax_growth = (pax_last / pax_base) ** (1 / years) - 1 if pax_base and pax_last and years else None

        seats_t12 = total("total_seats", lambda m: m in t12)
        seats_p12 = total("total_seats", lambda m: m in p12)
        pax_t12 = total("total_passengers", lambda m: m in t12)
        dep_t12 = total("total_departures", lambda m: m in t12)
        intl_t12 = total("outbound_international", lambda m: m in t12)
        intl_pax_t12 = total("outbound_international_1", lambda m: m in t12)
        freight_t12 = total("total_freight_lbs", lambda m: m in t12) + total("total_mail_lbs", lambda m: m in t12)
        dist = [_num(r.get("total_distance_flight_sm")) for r in rs if r["reporting_month"][:7] in t12 and r.get("total_distance_flight_sm")]
        n_t12 = sum(1 for r in rs if r["reporting_month"][:7] in t12)

        out[code] = {
            "name": rs[0].get("origin_airport_name"),
            "pax_growth": round(pax_growth, 4) if pax_growth is not None else None,
            "load_factor": round(pax_t12 / seats_t12, 4) if seats_t12 else None,
            "seat_growth": round(seats_t12 / seats_p12 - 1, 4) if seats_p12 else None,
            "scale": int(pax_t12),
            "intl_share": round(intl_t12 / dep_t12, 4) if dep_t12 else None,
            "intl_pax_share": round(intl_pax_t12 / pax_t12, 4) if pax_t12 else None,
            "freight_lbs": int(freight_t12),
            "avg_stage_mi": round(sum(dist) / len(dist)) if dist else None,
            "months_in_window": n_t12,
            "pax_base_year": int(pax_base),
            "pax_last_full_year": int(pax_last),
        }
    return {
        "source": "BTS T-100 by origin airport (all commercial service incl. cargo carriers), live",
        "latest_month": latest,
        "growth_window": f"{BASE_YEAR}-{last_full_year}",
        "trailing_12_months": f"{t12[0]} to {t12[-1]}",
        "definitions": {
            "pax_growth": f"CAGR of total passengers, calendar {BASE_YEAR} to {last_full_year}",
            "load_factor": "passengers / seats over the trailing 12 months",
            "seat_growth": "seats in the trailing 12 months vs the 12 months before (not a CAGR)",
            "scale": "total passengers (departing, all carriers) in the trailing 12 months; not FAA enplanements",
            "intl_share": "international departures / all departures, trailing 12 months (includes cargo flights)",
            "intl_pax_share": "international passengers / all passengers, trailing 12 months (cargo-free; a big gap below intl_share means the international flights are mostly freighters)",
            "freight_lbs": "freight + mail pounds departed, trailing 12 months (context only, not scored)",
            "avg_stage_mi": "mean of monthly average flight distance, statute miles, trailing 12 months",
        },
        "airports": out,
    }


def fetch_t100(codes: list[str]) -> dict:
    """Tool `get_airport_stats`: one live Socrata query for the given IATA codes since BASE_YEAR,
    aggregated by `t100_kpis`. Network or HTTP failures come back as {"error": ...}."""
    codes = sorted({c.strip().upper() for c in codes if c.strip()})
    if not codes:
        return {"error": "no airport codes given"}
    quoted = ",".join(f"'{c}'" for c in codes)
    params = {
        "$select": T100_FIELDS,
        "$where": f"origin_airport_code in ({quoted}) AND reporting_month >= '{BASE_YEAR}-01-01'",
        "$order": "reporting_month",
        "$limit": 50000,
    }
    try:
        r = httpx.get(T100_URL, params=params, timeout=TIMEOUT)
        r.raise_for_status()
        rows = r.json()
    except httpx.HTTPError as e:
        return {"error": f"BTS T-100 request failed: {e}"}
    result = t100_kpis(rows)
    if not result:
        return {"error": f"no T-100 rows for {codes}", "airports": {}}
    missing = [c for c in codes if c not in result["airports"]]
    if missing:
        result["not_found"] = missing
    return result


# ---- FAA NAS status ------------------------------------------------------------------------

def severity(kind: str) -> int:
    """Map an FAA event category to severity: 2 = ground stop (flights held at origin), 1 = any
    other active program (ground delay program, closure NOTAM, general delay notice)."""
    return 2 if "ground stop" in kind.lower() else 1


def parse_nas(text: str) -> tuple[str, list[dict]]:
    """Parse the FAA NAS status XML into (update_time, events); one event per airport per
    Delay_type block, with reason, average/max delay and start/end where the feed gives them."""
    root = ET.fromstring(text)
    update = (root.findtext("Update_Time") or "").strip()
    events = []
    for dt in root.findall("Delay_type"):
        kind = (dt.findtext("Name") or "unknown").strip()
        for entry in dt.iter():
            arpt = entry.find("ARPT")
            if arpt is None:
                continue
            sub = entry.find("Arrival_Departure")
            events.append({
                "code": (arpt.text or "").strip().upper(),
                "type": kind,
                "reason": (entry.findtext("Reason") or "").strip() or None,
                "avg_delay": (entry.findtext("Avg") or "").strip() or None,
                "max_delay": ((entry.findtext("Max") or (sub.findtext("Max") if sub is not None else "") or "").strip() or None),
                "start": (entry.findtext("Start") or "").strip() or None,
                "end": ((entry.findtext("Reopen") or entry.findtext("End_Time") or "").strip() or None),
            })
    return update, events


def fetch_nas(codes: list[str]) -> dict:
    """Tool `get_live_status`: fetch the whole FAA NAS feed (it is not filterable) and return, per
    requested code, the highest severity among its active events plus the events themselves."""
    codes = sorted({c.strip().upper() for c in codes if c.strip()})
    try:
        r = httpx.get(NAS_URL, timeout=TIMEOUT)
        r.raise_for_status()
        update, events = parse_nas(r.text)
    except (httpx.HTTPError, ET.ParseError) as e:
        return {"error": f"FAA NAS request failed: {e}"}
    airports = {}
    for c in codes:
        mine = [e for e in events if e["code"] == c]
        sev = max((severity(e["type"]) for e in mine), default=0)
        airports[c] = {"delay": sev, "events": mine}
    return {
        "source": "FAA NAS airport status, live now (absence from the feed is not proof of no delays)",
        "as_of": update,
        "delay_scale": "0 = nothing active, 1 = delay program or closure notice (read the reason: closure NOTAMs are often general-aviation only), 2 = ground stop",
        "airports": airports,
    }
