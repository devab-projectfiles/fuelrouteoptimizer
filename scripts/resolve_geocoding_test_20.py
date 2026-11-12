"""Resolve the 20-row sample with Geoapify Geocoding + fuel Places APIs.

This script is intentionally limited to data/geocoding_test_20.csv. It writes
new raw responses and a review CSV without modifying the source or 1,000-row
geocoding batch.
"""

import csv
import json
import os
import re
import time
from difflib import SequenceMatcher
from pathlib import Path

import requests
from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parents[1]
INPUT_FILE = BASE_DIR / "data" / "geocoding_test_20.csv"
OUTPUT_FILE = BASE_DIR / "data" / "geocoding_test_20_api_matches.csv"
RAW_FILE = BASE_DIR / "data" / "geocoding_test_20_api_results.json"
SUMMARY_FILE = BASE_DIR / "data" / "geocoding_test_20_api_summary.json"
GEOCODE_URL = "https://api.geoapify.com/v1/geocode/search"
PLACES_URL = "https://api.geoapify.com/v2/places"
FUEL_CATEGORY = "service.vehicle.fuel"
SEARCH_RADIUS_METERS = 25_000

BRAND_GROUPS = {
    "love_s": {"love s", "loves", "love s travel stop"},
    "pilot_flying_j": {"pilot", "flying j", "pilot flying j", "one9"},
    "circle_k": {"circle k"},
    "shell": {"shell"},
    "citgo": {"citgo"},
    "maplefields": {"maplefields"},
    "town_pump": {"town pump"},
    "becks": {"beck s", "becks"},
    "good_to_go": {"good to go"},
    "sudden_service": {"sudden service"},
    "millers": {"millers"},
    "road_mart": {"road mart"},
    "pilot": {"pilot"},
    "jacksons": {"jackson s", "jacksons"},
    "git_n_go": {"git n go"},
    "geo_h_green": {"geo h green"},
    "flint_hills": {"flint hills"},
    "el_centro": {"el centro"},
}

GENERIC_TERMS = {
    "travel", "stop", "stops", "center", "centers", "plaza", "truck",
    "fuel", "mart", "food", "store", "stores", "convenience", "gas",
    "station", "dba", "the", "traveling", "travelers",
}


def norm(value):
    value = re.sub(r"[^a-z0-9\s]", " ", str(value or "").lower())
    return " ".join(value.split())


def brand_group(value):
    words = set(norm(value).split())
    phrase = norm(value)
    for group, aliases in BRAND_GROUPS.items():
        for alias in aliases:
            alias_words = norm(alias).split()
            if alias_words and all(word in words for word in alias_words):
                return group
    return None


def name_score(first, second):
    first_words = [w for w in norm(first).split() if w not in GENERIC_TERMS and not w.isdigit()]
    second_words = [w for w in norm(second).split() if w not in GENERIC_TERMS and not w.isdigit()]
    a, b = " ".join(first_words), " ".join(second_words)
    if not a or not b:
        return 0.0
    group_a, group_b = brand_group(first), brand_group(second)
    if group_a and group_a == group_b:
        return 1.0
    return SequenceMatcher(None, a, b).ratio()


def location_from_input(address):
    parts = [part.strip() for part in address.split(",")]
    if len(parts) >= 4:
        return parts[-3], parts[-2]
    return "", ""


def read_input():
    with INPUT_FILE.open(encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def request_json(session, url, params):
    try:
        response = session.get(url, params=params, timeout=35)
    except requests.RequestException:
        return None, "network_error"
    if not response.ok:
        return None, f"http_{response.status_code}"
    try:
        return response.json(), None
    except ValueError:
        return None, "invalid_json"


def candidate_rank(station_name, city, state, candidate):
    props = candidate.get("properties", candidate)
    candidate_name = props.get("name") or props.get("address_line1") or ""
    candidate_city = props.get("city") or ""
    candidate_state = props.get("state_code") or ""
    if not candidate_state:
        candidate_state = props.get("state", "")
    score = name_score(station_name, candidate_name)
    same_state = norm(candidate_state) == norm(state) or norm(state) in norm(candidate_state)
    same_city = norm(candidate_city) == norm(city) or norm(city) in norm(candidate_city)
    country = norm(props.get("country_code")) in {"us", ""}
    categories = props.get("categories", [])
    fuel_poi = any(cat == FUEL_CATEGORY for cat in categories)
    return {
        "score": score,
        "same_state": same_state,
        "same_city": same_city,
        "country_ok": country,
        "fuel_poi": fuel_poi,
        "name": candidate_name,
        "city": candidate_city,
        "state": candidate_state,
        "latitude": props.get("lat") or (candidate.get("geometry", {}).get("coordinates", [None, None])[1]),
        "longitude": props.get("lon") or (candidate.get("geometry", {}).get("coordinates", [None, None])[0]),
        "address": props.get("formatted") or props.get("address_line2") or "",
        "result_type": props.get("result_type", ""),
        "confidence": props.get("rank", {}).get("confidence", ""),
        "categories": categories,
    }


def choose_geocode(station, candidates, city, state):
    scored = [candidate_rank(station, city, state, item) for item in candidates]
    scored.sort(key=lambda item: (
        item["country_ok"], item["same_state"], item["same_city"],
        item["fuel_poi"], item["score"],
        float(item["confidence"] or 0),
    ), reverse=True)
    return scored[0] if scored else None


def choose_places(station, places, city, state):
    scored = [candidate_rank(station, city, state, item) for item in places]
    local = [item for item in scored if item["country_ok"] and item["same_state"] and item["same_city"] and item["fuel_poi"]]
    local.sort(key=lambda item: (item["score"], item["name"] != ""), reverse=True)
    if not local:
        return None, 0
    best = local[0]
    tied_brand = [item for item in local if item["score"] >= max(0.8, best["score"] - 0.03)]
    return best, len(tied_brand)


def main():
    load_dotenv(BASE_DIR / ".env", override=True)
    api_key = os.getenv("GEOAPIFY_API_KEY")
    if not api_key:
        raise SystemExit("GEOAPIFY_API_KEY is missing from the project .env file.")

    stations = read_input()
    if len(stations) != 20:
        raise SystemExit(f"Expected the 20-row sample, found {len(stations)} rows; stopping without API calls.")

    session = requests.Session()
    raw = json.loads(RAW_FILE.read_text(encoding="utf-8")) if RAW_FILE.exists() else {}
    if OUTPUT_FILE.exists():
        with OUTPUT_FILE.open(encoding="utf-8-sig", newline="") as file:
            output = list(csv.DictReader(file))
    else:
        output = []
    completed = {row["station_id"] for row in output}
    counts = {"strong_match": 0, "candidate_only": 0, "unmatched": 0, "api_error": 0}

    for index, station in enumerate(stations):
        station_id = station["station_id"]
        if station_id in completed:
            continue
        station_name = station["station_name"]
        address = station.get("original_address", "")
        city, state = location_from_input(address)
        query = f"{station_name}, {city}, {state}, United States"
        address_lat = station.get("address_latitude")
        address_lon = station.get("address_longitude")
        bias = f"proximity:{address_lon},{address_lat}" if address_lat and address_lon else "proximity:-100,39"
        geocode, geocode_error = request_json(session, GEOCODE_URL, {
            "text": query,
            "apiKey": api_key,
            "format": "json",
            "limit": 5,
            "filter": "countrycode:us",
            "bias": bias,
        })
        geocode_results = (geocode or {}).get("results", [])
        best_geo = choose_geocode(station_name, geocode_results, city, state)

        # Search in a city-sized radius around the station-name hit when present;
        # otherwise use the sample's already stored address-geocode point.
        anchor_lat = best_geo and best_geo["latitude"]
        anchor_lon = best_geo and best_geo["longitude"]
        if not anchor_lat or not anchor_lon:
            anchor_lat = station.get("address_latitude")
            anchor_lon = station.get("address_longitude")
        places_data, places_error = (None, "no_anchor")
        if anchor_lat and anchor_lon:
            places_data, places_error = request_json(session, PLACES_URL, {
                "categories": FUEL_CATEGORY,
                "filter": f"circle:{anchor_lon},{anchor_lat},{SEARCH_RADIUS_METERS}",
                "bias": f"proximity:{anchor_lon},{anchor_lat}",
                "limit": 500,
                "lang": "en",
                "apiKey": api_key,
            })
        place_features = (places_data or {}).get("features", [])
        best_place, near_ties = choose_places(station_name, place_features, city, state)

        # A match needs an actual fuel POI, the target city/state and either a
        # strong name hit or a name-geocoded fuel POI. General proximity alone
        # is deliberately not counted as an identity match.
        geo_strong = bool(best_geo and best_geo["fuel_poi"] and best_geo["same_city"]
                          and best_geo["same_state"] and best_geo["score"] >= 0.65)
        place_strong = bool(best_place and best_place["score"] >= 0.80 and near_ties == 1)
        if geo_strong or place_strong:
            status = "strong_match"
            counts["strong_match"] += 1
        elif best_geo or best_place:
            status = "candidate_only"
            counts["candidate_only"] += 1
        else:
            status = "unmatched"
            counts["unmatched"] += 1
        if geocode_error or places_error not in {None, "no_anchor"}:
            counts["api_error"] += 1

        chosen = best_place or best_geo or {}
        raw[station_id] = {
            "query": query,
            "geocode_error": geocode_error,
            "geocode_called": True,
            "geocode_results": geocode_results,
            "places_error": places_error,
            "places_called": places_data is not None or (anchor_lat and anchor_lon),
            "places": place_features,
        }
        output.append({
            "station_id": station_id,
            "station_name": station_name,
            "input_address": address,
            "city": city,
            "state": state,
            "geocode_query": query,
            "geocode_result_name": best_geo["name"] if best_geo else "",
            "geocode_result_address": best_geo["address"] if best_geo else "",
            "geocode_result_type": best_geo["result_type"] if best_geo else "",
            "geocode_confidence": best_geo["confidence"] if best_geo else "",
            "geocode_name_score": round(best_geo["score"], 3) if best_geo else "",
            "geocode_is_fuel_poi": best_geo["fuel_poi"] if best_geo else False,
            "fuel_poi_count_in_city_radius": len(place_features),
            "best_fuel_poi_name": best_place["name"] if best_place else "",
            "best_fuel_poi_address": best_place["address"] if best_place else "",
            "best_fuel_poi_latitude": best_place["latitude"] if best_place else "",
            "best_fuel_poi_longitude": best_place["longitude"] if best_place else "",
            "best_fuel_poi_name_score": round(best_place["score"], 3) if best_place else "",
            "near_tied_brand_candidates": near_ties,
            "matched_latitude": chosen.get("latitude", ""),
            "matched_longitude": chosen.get("longitude", ""),
            "match_status": status,
            "match_reason": (
                "Fuel POI and station name agree in the same city/state."
                if status == "strong_match" else
                "POI returned, but identity evidence is insufficient or ambiguous."
                if status == "candidate_only" else
                "No usable named fuel POI found in the search area."
            ),
            "geocode_api_status": geocode_error or "ok",
            "places_api_status": places_error or "ok",
        })
        # Persist each completed row so an interruption does not force repeat
        # API calls or lose earlier responses.
        RAW_FILE.write_text(json.dumps(raw, indent=2), encoding="utf-8")
        with OUTPUT_FILE.open("w", encoding="utf-8", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=list(output[0]))
            writer.writeheader()
            writer.writerows(output)
        print(f"{index + 1}/20 {station_id}: {status}")
        time.sleep(0.15)

    with OUTPUT_FILE.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(output[0]))
        writer.writeheader()
        writer.writerows(output)
    RAW_FILE.write_text(json.dumps(raw, indent=2), encoding="utf-8")
    final_counts = {name: sum(row["match_status"] == name for row in output)
                    for name in ("strong_match", "candidate_only", "unmatched")}
    api_error_rows = sum(
        bool(item.get("geocode_error"))
        or item.get("places_error") not in {None, "no_anchor"}
        for item in raw.values()
    )
    summary = {
        "sample_rows": len(stations),
        "api_calls_expected": len(stations) * 2,
        "api_calls_actual": sum(
            int(item.get("geocode_called", False)) + int(item.get("places_called", False))
            for item in raw.values()
        ),
        "high_confidence_matches": final_counts["strong_match"],
        "high_confidence_match_percent": round(final_counts["strong_match"] * 100 / len(stations), 1),
        "candidate_only": final_counts["candidate_only"],
        "unmatched": final_counts["unmatched"],
        "api_error_rows": api_error_rows,
        "match_definition": "Same-city/state fuel POI with a strong station/brand name match; ambiguous candidates are not counted.",
        "outputs": [str(OUTPUT_FILE.relative_to(BASE_DIR)), str(RAW_FILE.relative_to(BASE_DIR))],
    }
    SUMMARY_FILE.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
