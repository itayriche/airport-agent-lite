"""Live data tools: BTS T-100 (Socrata) and FAA NAS status. No cache, no snapshots, plain Python."""

import xml.etree.ElementTree as ET
from collections import defaultdict

import httpx

T100_URL = "https://data.bts.gov/resource/r495-tyji.json"
NAS_URL = "https://nasstatus.faa.gov/api/airport-status-information"
T100_FIELDS = (
    "origin_airport_code,reporting_month,total_departures,total_passengers,total_seats,"
    "outbound_international,total_distance_flight_sm,origin_airport_name"
)
BASE_YEAR = 2019  # pre-COVID anchor for growth
TIMEOUT = 30


# ---- BTS T-100 -----------------------------------------------------------------------------

def _num(v):
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
        dist = [_num(r.get("total_distance_flight_sm")) for r in rs if r["reporting_month"][:7] in t12 and r.get("total_distance_flight_sm")]
        n_t12 = sum(1 for r in rs if r["reporting_month"][:7] in t12)

        out[code] = {
            "name": rs[0].get("origin_airport_name"),
            "pax_growth": round(pax_growth, 4) if pax_growth is not None else None,
            "load_factor": round(pax_t12 / seats_t12, 4) if seats_t12 else None,
            "seat_growth": round(seats_t12 / seats_p12 - 1, 4) if seats_p12 else None,
            "scale": int(pax_t12),
            "intl_share": round(intl_t12 / dep_t12, 4) if dep_t12 else None,
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
            "avg_stage_mi": "mean of monthly average flight distance, statute miles, trailing 12 months",
        },
        "airports": out,
    }


def fetch_t100(codes: list[str]) -> dict:
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
    """2 = ground stop, 1 = any other active program (delay program, closure NOTAM)."""
    return 2 if "ground stop" in kind.lower() else 1


def parse_nas(text: str) -> tuple[str, list[dict]]:
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
