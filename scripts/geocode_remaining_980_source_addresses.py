"""Independently geocode the source route/exit address for the 980-row remainder.

This produces address-query coordinates only. It does not claim station identity;
the follow-up audit checks locality and whether a returned fuel POI is nearby.
"""

import csv
import json
import os
import time
from collections import Counter
from pathlib import Path

import requests
from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parents[1]
CANDIDATES_FILE = BASE_DIR / "data" / "geocoded_station_candidates.csv"
PILOT_FILE = BASE_DIR / "data" / "geocoding_test_20.csv"
STATE_FILE = BASE_DIR / "data" / "geocoding_rest_980_address_batch_progress.json"
RAW_FILE = BASE_DIR / "data" / "geocoding_rest_980_address_geocodes.jsonl"
OUTPUT_FILE = BASE_DIR / "data" / "geocoding_rest_980_address_geocodes.csv"
SUMMARY_FILE = BASE_DIR / "data" / "geocoding_rest_980_address_summary.json"
BATCH_URL = "https://api.geoapify.com/v1/batch/geocode/search"
STATE_NAMES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California",
    "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware", "FL": "Florida", "GA": "Georgia",
    "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas",
    "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts",
    "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi", "MO": "Missouri", "MT": "Montana",
    "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico",
    "NY": "New York", "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma",
    "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota",
    "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia", "WA": "Washington",
    "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming", "DC": "District of Columbia",
}
PRECISION = {"amenity": 7, "building": 6, "street": 5, "suburb": 4, "locality": 3,
             "city": 2, "postcode": 2, "county": 1, "state": 0, "country": -1}


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as source:
        return list(csv.DictReader(source))


def norm(value):
    return " ".join(str(value or "").casefold().replace(",", " ").split())


def load_jsonl():
    records = {}
    if RAW_FILE.exists():
        with RAW_FILE.open(encoding="utf-8") as source:
            for line in source:
                if line.strip():
                    item = json.loads(line)
                    records[item["station_id"]] = item
    return records


def append_jsonl(item):
    with RAW_FILE.open("a", encoding="utf-8") as output:
        output.write(json.dumps(item, separators=(",", ":"), ensure_ascii=False) + "\n")


def result_list(item):
    if isinstance(item, list):
        return item
    if isinstance(item, dict):
        if isinstance(item.get("results"), list):
            return item["results"]
        if item.get("lat") is not None or item.get("lon") is not None:
            return [item]
        if isinstance(item.get("result"), dict):
            return result_list(item["result"])
    return []


def locality_state_match(item, station):
    city = norm(item.get("city"))
    state = norm(item.get("state_code") or item.get("state"))
    expected_state = norm(station["original_state"])
    full_state = norm(STATE_NAMES.get(station["original_state"].upper(), station["original_state"]))
    same_city = city == norm(station["original_city"])
    same_state = state in {expected_state, full_state}
    country_ok = norm(item.get("country_code")) == "us"
    return same_city, same_state, country_ok


def choose(results, station):
    ranked = []
    for item in results:
        same_city, same_state, country_ok = locality_state_match(item, station)
        result_type = item.get("result_type", "")
        rank_conf = float(item.get("rank", {}).get("confidence", 0) or 0)
        ranked.append((country_ok, same_state, same_city, PRECISION.get(result_type, -1), rank_conf, item))
    ranked.sort(key=lambda value: value[:5], reverse=True)
    return ranked[0][5] if ranked else None


def main():
    load_dotenv(BASE_DIR / ".env", override=True)
    api_key = os.getenv("GEOAPIFY_API_KEY")
    if not api_key:
        raise SystemExit("GEOAPIFY_API_KEY is missing from .env")

    rows = [row for row in read_csv(CANDIDATES_FILE)
            if row["station_id"] not in {item["station_id"] for item in read_csv(PILOT_FILE)}]
    if len(rows) != 980:
        raise SystemExit(f"Expected 980 rows outside pilot; found {len(rows)}")

    raw = load_jsonl()
    missing = [row for row in rows if row["station_id"] not in raw]
    state = json.loads(STATE_FILE.read_text(encoding="utf-8")) if STATE_FILE.exists() else {}
    session = requests.Session()
    if missing:
        if state.get("job_id"):
            job_id = state["job_id"]
            print("Resuming saved address-geocoding batch.", flush=True)
        else:
            queries = [f"{row['original_address']}, {row['original_city']}, {row['original_state']}, United States"
                       for row in missing]
            response = session.post(BATCH_URL, params={"apiKey": api_key, "lang": "en", "countrycodes": "us"},
                                    json=queries, timeout=90)
            if response.status_code != 202:
                raise RuntimeError(f"Batch submission failed: HTTP {response.status_code}")
            job_id = response.json()["id"]
            STATE_FILE.write_text(json.dumps({"job_id": job_id, "rows": len(missing)}, indent=2), encoding="utf-8")
            print(f"Address batch submitted for {len(missing)} rows.", flush=True)

        started = time.monotonic()
        while True:
            response = session.get(BATCH_URL, params={"id": job_id, "apiKey": api_key, "format": "json"}, timeout=90)
            if response.status_code == 200:
                batch_results = response.json()
                break
            if response.status_code != 202:
                raise RuntimeError(f"Batch retrieval failed: HTTP {response.status_code}")
            if time.monotonic() - started > 45 * 60:
                raise TimeoutError("Batch remains active; job id is saved for resume.")
            print("Address batch is processing; polling again in 30 seconds.", flush=True)
            time.sleep(30)
        if len(batch_results) != len(missing):
            raise RuntimeError(f"Expected {len(missing)} address results, got {len(batch_results)}")
        for row, result in zip(missing, batch_results):
            record = {"station_id": row["station_id"], "query": row["original_address"], "result": result}
            append_jsonl(record)
            raw[row["station_id"]] = record
        STATE_FILE.write_text(json.dumps({"job_id": None, "rows": len(missing), "complete": True}, indent=2),
                              encoding="utf-8")

    output = []
    type_counts = Counter()
    for station in rows:
        record = raw.get(station["station_id"], {})
        results = result_list(record.get("result"))
        best = choose(results, station)
        same_city, same_state, country_ok = locality_state_match(best or {}, station)
        result_type = (best or {}).get("result_type", "")
        type_counts[result_type or "not_found"] += 1
        try:
            old_lat, old_lon = float(station["latitude"]), float(station["longitude"])
            new_lat, new_lon = float(best["lat"]), float(best["lon"])
            from math import asin, cos, radians, sin, sqrt
            p1, p2 = radians(old_lat), radians(new_lat)
            dp, dl = p2-p1, radians(new_lon-old_lon)
            distance = 2*6371000*asin(sqrt(sin(dp/2)**2+cos(p1)*cos(p2)*sin(dl/2)**2))
            distance = round(distance, 1)
        except (TypeError, ValueError, KeyError):
            distance = ""
        if not best or best.get("lat") is None or best.get("lon") is None:
            status = "not_found"
        elif not country_ok or not same_state:
            status = "state_or_country_mismatch"
        elif not same_city:
            status = "nearby_city_mismatch"
        elif result_type in {"amenity", "building", "street"}:
            status = "same_city_precise_address_result"
        else:
            status = "same_city_low_precision_result"
        output.append({
            "station_id": station["station_id"], "station_name": station["original_name"],
            "source_route_or_exit": station["original_address"], "expected_city": station["original_city"],
            "expected_state": station["original_state"], "query": record.get("query", ""),
            "geocoded_name": (best or {}).get("name", ""), "geocoded_address": (best or {}).get("formatted", ""),
            "result_type": result_type, "confidence": (best or {}).get("rank", {}).get("confidence", ""),
            "match_type": (best or {}).get("rank", {}).get("match_type", ""),
            "geocoder_city": (best or {}).get("city", ""), "geocoder_state": (best or {}).get("state", ""),
            "same_city": same_city, "same_state": same_state, "country_is_us": country_ok,
            "latitude": (best or {}).get("lat", ""), "longitude": (best or {}).get("lon", ""),
            "distance_from_previous_geocode_m": distance, "address_resolution_status": status,
            "result_count": len(results),
        })

    with OUTPUT_FILE.open("w", encoding="utf-8", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=list(output[0]))
        writer.writeheader()
        writer.writerows(output)
    counts = Counter(row["address_resolution_status"] for row in output)
    strong_location = counts["same_city_precise_address_result"]
    summary = {
        "input_rows": len(rows), "rows_with_address_batch_response": len(raw),
        "address_resolution_status_counts": dict(counts), "result_type_counts": dict(type_counts),
        "same_city_precise_address_rows": strong_location,
        "same_city_precise_address_percent": round(100 * strong_location / len(rows), 1),
        "interpretation": "This measures whether the original route/exit query geocodes to a precise amenity/building/street result in the expected city and state. It does not by itself verify station identity or current operation.",
        "outputs": [str(OUTPUT_FILE.relative_to(BASE_DIR)), str(RAW_FILE.relative_to(BASE_DIR))],
    }
    SUMMARY_FILE.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    main()
