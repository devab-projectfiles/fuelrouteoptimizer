"""Geocode independently sourced site addresses for the 20-row evaluation."""

import csv
import json
import os
import time
from math import asin, cos, radians, sin, sqrt
from pathlib import Path

import requests
from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parents[1]
INPUT_FILE = BASE_DIR / "data" / "geocoding_test_20.csv"
REFERENCE_FILE = BASE_DIR / "data" / "geocoding_test_20_reference_addresses.csv"
OUTPUT_FILE = BASE_DIR / "data" / "geocoding_test_20_reference_geocodes.csv"
RAW_FILE = BASE_DIR / "data" / "geocoding_test_20_reference_geocodes.json"
SUMMARY_FILE = BASE_DIR / "data" / "geocoding_test_20_reference_summary.json"
GEOCODE_URL = "https://api.geoapify.com/v1/geocode/search"
STATE_NAMES = {
    "AL": "Alabama", "AR": "Arkansas", "CA": "California", "GA": "Georgia",
    "IA": "Iowa", "IL": "Illinois", "IN": "Indiana", "KS": "Kansas",
    "MT": "Montana", "TN": "Tennessee", "UT": "Utah", "VA": "Virginia",
    "VT": "Vermont", "ID": "Idaho",
}


def read_rows(path):
    with path.open(encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def norm(value):
    return " ".join(str(value or "").lower().replace(",", " ").split())


def distance_meters(lat1, lon1, lat2, lon2):
    earth_radius = 6_371_000
    lat1, lon1, lat2, lon2 = map(radians, map(float, (lat1, lon1, lat2, lon2)))
    delta_lat, delta_lon = lat2 - lat1, lon2 - lon1
    value = sin(delta_lat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(delta_lon / 2) ** 2
    return 2 * earth_radius * asin(sqrt(value))


def choose_result(results, city, state):
    full_state = STATE_NAMES.get(state.upper(), state)
    scored = []
    for result in results:
        same_city = norm(result.get("city")) == norm(city)
        state_code = result.get("state_code", "")
        state_name = result.get("state", "")
        same_state = norm(state_code) == norm(state) or norm(state_name) == norm(full_state)
        country_ok = norm(result.get("country_code")) == "us"
        confidence = float(result.get("rank", {}).get("confidence", 0) or 0)
        scored.append((country_ok, same_state, same_city, confidence, result))
    scored.sort(key=lambda item: item[:4], reverse=True)
    return scored[0][4] if scored else None


def main():
    load_dotenv(BASE_DIR / ".env", override=True)
    api_key = os.getenv("GEOAPIFY_API_KEY")
    if not api_key:
        raise SystemExit("GEOAPIFY_API_KEY is missing from the project .env file.")

    stations = {row["station_id"]: row for row in read_rows(INPUT_FILE)}
    references = read_rows(REFERENCE_FILE)
    raw = json.loads(RAW_FILE.read_text(encoding="utf-8")) if RAW_FILE.exists() else {}
    if OUTPUT_FILE.exists():
        output = read_rows(OUTPUT_FILE)
    else:
        output = []
    completed = {row["station_id"] for row in output}
    session = requests.Session()

    for reference in references:
        station_id = reference["station_id"]
        if station_id in completed:
            continue
        station = stations[station_id]
        city_parts = [part.strip() for part in station["original_address"].split(",")]
        city = city_parts[-3] if len(city_parts) >= 4 else ""
        state = city_parts[-2] if len(city_parts) >= 4 else ""
        reference_address = reference["reference_address"]
        api_error = ""
        results = []
        if reference_address:
            try:
                response = session.get(GEOCODE_URL, params={
                    "text": reference_address,
                    "apiKey": api_key,
                    "format": "json",
                    "limit": 5,
                    "filter": "countrycode:us",
                }, timeout=35)
                if response.ok:
                    results = response.json().get("results", [])
                else:
                    api_error = f"http_{response.status_code}"
            except requests.RequestException:
                api_error = "network_error"
        else:
            api_error = "no_reference_address"

        best = choose_result(results, city, state)
        original_lat = station.get("address_latitude")
        original_lon = station.get("address_longitude")
        distance = None
        if best and original_lat and original_lon:
            distance = distance_meters(original_lat, original_lon, best["lat"], best["lon"])

        same_state = bool(best and (
            norm(best.get("state_code")) == norm(state)
            or norm(best.get("state")) == norm(STATE_NAMES.get(state.upper(), state))
        ))
        same_city = bool(best and norm(best.get("city")) == norm(city))
        has_location = bool(best and best.get("lat") is not None and best.get("lon") is not None)
        source_address_match = reference["identity_status"] == "address_found" and same_state and same_city and has_location
        if source_address_match:
            coordinate_status = "source_address_geocoded"
        elif reference["identity_status"] == "ambiguous":
            coordinate_status = "ambiguous_source_identity"
        elif reference["identity_status"] == "unresolved":
            coordinate_status = "unresolved_source_identity"
        elif api_error:
            coordinate_status = "api_error"
        else:
            coordinate_status = "geocoder_city_state_mismatch"

        raw[station_id] = {"reference_address": reference_address, "api_error": api_error,
                           "results": results}
        output.append({
            "station_id": station_id,
            "station_name": station["station_name"],
            "input_address": station["original_address"],
            "reference_address": reference_address,
            "reference_source": reference["reference_source"],
            "identity_status": reference["identity_status"],
            "source_note": reference["status_note"],
            "geocoded_address": best.get("formatted", "") if best else "",
            "geocoder_result_type": best.get("result_type", "") if best else "",
            "geocoder_confidence": best.get("rank", {}).get("confidence", "") if best else "",
            "geocoder_match_type": best.get("rank", {}).get("match_type", "") if best else "",
            "geocoder_city": best.get("city", "") if best else "",
            "geocoder_state": best.get("state", "") if best else "",
            "latitude": best.get("lat", "") if best else "",
            "longitude": best.get("lon", "") if best else "",
            "distance_from_old_address_result_m": round(distance, 1) if distance is not None else "",
            "coordinate_status": coordinate_status,
            "api_status": api_error or "ok",
        })
        with OUTPUT_FILE.open("w", encoding="utf-8", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=list(output[0]))
            writer.writeheader()
            writer.writerows(output)
        RAW_FILE.write_text(json.dumps(raw, indent=2), encoding="utf-8")
        print(f"{len(output)}/20 {station_id}: {coordinate_status}")
        time.sleep(0.15)

    successes = sum(row["coordinate_status"] == "source_address_geocoded" for row in output)
    summary = {
        "sample_rows": len(references),
        "addresses_supported_by_traceable_location_sources": sum(r["identity_status"] == "address_found" for r in references),
        "source_address_geocoded_rows": successes,
        "source_address_geocoded_percent": round(100 * successes / len(references), 1),
        "ambiguous_rows": sum(r["identity_status"] == "ambiguous" for r in references),
        "unresolved_rows": sum(r["identity_status"] == "unresolved" for r in references),
        "definition": "A row counts when a source associates the station identity with an address and Geoapify geocodes that address into the input city and state. This measures location resolution, not fuel-price brand eligibility or current operating status.",
        "api_calls": sum(bool(r["reference_address"]) for r in references),
        "api_errors": sum(bool(item.get("api_error")) for item in raw.values()),
    }
    SUMMARY_FILE.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
