"""Resolve the 980 rows outside the 20-row pilot against Geoapify fuel POIs.

The source CSVs are read-only inputs. This script writes separate API response,
POI-candidate, station-decision, and summary files. Geocoded streets/cities are
search anchors only; they are never treated as station coordinates by default.
"""

import csv
import json
import os
import re
import time
from collections import Counter
from difflib import SequenceMatcher
from math import asin, cos, radians, sin, sqrt
from pathlib import Path

import requests
from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parents[1]
STATIONS_FILE = BASE_DIR / "data" / "fuel_stations_preprocessed.csv"
CANDIDATES_FILE = BASE_DIR / "data" / "geocoded_station_candidates.csv"
PILOT_FILE = BASE_DIR / "data" / "geocoding_test_20.csv"
BATCH_STATE_FILE = BASE_DIR / "data" / "geocoding_rest_980_batch_progress.json"
BATCH_GEOCODES_FILE = BASE_DIR / "data" / "geocoding_rest_980_geocodes.jsonl"
API_RESULTS_FILE = BASE_DIR / "data" / "geocoding_rest_980_api_results.jsonl"
MATCHES_FILE = BASE_DIR / "data" / "geocoding_rest_980_matches.csv"
POIS_FILE = BASE_DIR / "data" / "geocoding_rest_980_poi_candidates.csv"
SUMMARY_FILE = BASE_DIR / "data" / "geocoding_rest_980_summary.json"

BATCH_URL = "https://api.geoapify.com/v1/batch/geocode/search"
PLACES_URL = "https://api.geoapify.com/v2/places"
FUEL_CATEGORY = "service.vehicle.fuel"
SEARCH_RADIUS_METERS = 25_000
PLACE_LIMIT = 20
REQUEST_PAUSE_SECONDS = 0.25
MAX_GEOCODE_BATCH_WAIT_SECONDS = 45 * 60

STATE_NAMES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas",
    "CA": "California", "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware",
    "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho",
    "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas",
    "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland",
    "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi",
    "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma",
    "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina",
    "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah",
    "VT": "Vermont", "VA": "Virginia", "WA": "Washington", "WV": "West Virginia",
    "WI": "Wisconsin", "WY": "Wyoming", "DC": "District of Columbia",
}

# This is deliberately a station-operator crosswalk, not an assumption that
# co-located fuel brands are interchangeable.
BRAND_GROUPS = {
    "love_s": {"love s", "loves"},
    "pilot_flying_j": {"pilot", "flying j", "pilot flying j", "one9"},
    "circle_k": {"circle k"},
    "citgo": {"citgo"}, "shell": {"shell"}, "conoco": {"conoco"},
    "chevron": {"chevron"}, "exxon": {"exxon"}, "mobil": {"mobil"},
    "exxonmobil": {"exxonmobil"}, "bp": {"bp"}, "sunoco": {"sunoco"},
    "marathon": {"marathon"}, "speedway": {"speedway"},
    "kwik_trip": {"kwik trip", "kwik star"}, "caseys": {"caseys", "casey s"},
    "murphy_usa": {"murphy usa"}, "murphy_express": {"murphy express"},
    "ta": {"ta", "travelcenters of america"}, "petro": {"petro"},
    "road_ranger": {"road ranger"}, "town_pump": {"town pump"},
    "maplefields": {"maplefields"}, "good_to_go": {"good to go"},
    "sudden_service": {"sudden service"}, "beck_s": {"beck s", "becks"},
    "road_mart": {"road mart"}, "quiktrip": {"quiktrip", "quicktrip"},
    "wawa": {"wawa"}, "racetrac": {"racetrac"}, "valero": {"valero"},
    "7_eleven": {"7 eleven", "7 eleven"}, "stinker": {"stinker"},
    "jacksons": {"jackson s", "jacksons"}, "git_n_go": {"git n go", "git go"},
    "town_pump": {"town pump"}, "flint_hills": {"flint hills"},
    "geo_h_green": {"geo h green"}, "millers": {"millers"},
    "el_centro": {"el centro"}, "roadys": {"roadys", "roadys"},
}

GENERIC_TERMS = {
    "travel", "stop", "stops", "center", "centers", "plaza", "truck",
    "fuel", "mart", "food", "store", "stores", "convenience", "gas",
    "station", "dba", "the", "travelers", "travel", "express", "service",
}


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def norm(value):
    return " ".join(re.sub(r"[^a-z0-9\s]", " ", str(value or "").lower()).split())


def name_tokens(value):
    return [word for word in norm(value).split() if word not in GENERIC_TERMS and not word.isdigit()]


def brand_group(value):
    words = set(norm(value).split())
    for group, aliases in BRAND_GROUPS.items():
        for alias in sorted(aliases, key=len, reverse=True):
            alias_words = norm(alias).split()
            if alias_words and all(word in words for word in alias_words):
                return group
    return None


def similarity(first, second):
    first_clean, second_clean = " ".join(name_tokens(first)), " ".join(name_tokens(second))
    if not first_clean or not second_clean:
        return 0.0
    first_brand, second_brand = brand_group(first), brand_group(second)
    if first_brand and first_brand == second_brand:
        return 1.0
    return SequenceMatcher(None, first_clean, second_clean).ratio()


def station_number(value):
    match = re.search(r"(?:#|\bstore\s*|\bnumber\s*)(\d{1,8})\b", str(value or ""), re.I)
    return match.group(1) if match else ""


def haversine_meters(lat1, lon1, lat2, lon2):
    earth_radius = 6_371_000
    lat1, lon1, lat2, lon2 = map(radians, map(float, (lat1, lon1, lat2, lon2)))
    dlat, dlon = lat2 - lat1, lon2 - lon1
    value = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return 2 * earth_radius * asin(sqrt(value))


def load_jsonl(path):
    records = {}
    if path.exists():
        with path.open(encoding="utf-8") as file:
            for line in file:
                if not line.strip():
                    continue
                row = json.loads(line)
                records[row["station_id"]] = row
    return records


def append_jsonl(path, record):
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(record, separators=(",", ":"), ensure_ascii=False) + "\n")


def extract_features(batch_item):
    if not batch_item:
        return []
    if isinstance(batch_item, list):
        return batch_item
    if isinstance(batch_item, dict):
        if isinstance(batch_item.get("results"), list):
            return batch_item["results"]
        if isinstance(batch_item.get("features"), list):
            return [feature.get("properties", feature) for feature in batch_item["features"]]
        if isinstance(batch_item.get("result"), dict):
            return extract_features(batch_item["result"])
        if batch_item.get("lat") is not None or batch_item.get("lon") is not None:
            return [batch_item]
    return []


def select_geocode_result(results, station):
    city, state = norm(station["original_city"]), station["original_state"].upper()
    full_state = norm(STATE_NAMES.get(state, state))
    ranked = []
    for item in results:
        item_city = norm(item.get("city"))
        item_state = norm(item.get("state_code") or item.get("state"))
        same_city = bool(item_city and (item_city == city or city in item_city))
        same_state = item_state in {norm(state), full_state}
        local = same_city and same_state and item.get("country_code", "us") == "us"
        score = similarity(station["original_name"], item.get("name") or item.get("formatted", ""))
        confidence = float(item.get("rank", {}).get("confidence", 0) or 0)
        result_type = item.get("result_type", "")
        # Favor the station-like name and same locality; use confidence only as
        # a tie-break because the pilot showed high street confidence can be wrong.
        ranked.append((local, score, result_type in {"amenity", "building"}, confidence, item))
    ranked.sort(key=lambda values: values[:4], reverse=True)
    return ranked[0][4] if ranked else None


def compact_poi(feature, station, anchor):
    props = feature.get("properties", feature)
    coordinates = feature.get("geometry", {}).get("coordinates", [])
    lat = props.get("lat") or (coordinates[1] if len(coordinates) > 1 else None)
    lon = props.get("lon") or (coordinates[0] if coordinates else None)
    distance = props.get("distance")
    if distance is None and anchor and lat is not None and lon is not None:
        distance = haversine_meters(anchor["lat"], anchor["lon"], lat, lon)
    raw = props.get("datasource", {}).get("raw", {})
    name = props.get("name") or props.get("address_line1") or ""
    brand = props.get("brand") or raw.get("brand") or ""
    state_code = props.get("state_code") or ""
    city = props.get("city") or ""
    poi_brand = brand_group(brand or name)
    station_brand = brand_group(station["original_name"])
    name_score = similarity(station["original_name"], name)
    same_city = norm(city) == norm(station["original_city"]) if city else False
    same_state = norm(state_code) == norm(station["original_state"])
    category_list = props.get("categories") or []
    fuel_type = any(category == FUEL_CATEGORY for category in category_list)
    number = station_number(station["original_name"])
    refs = " ".join(str(raw.get(key, "")) for key in (
        "ref", "operator:ref", "brand:store", "name", "brand", "website",
    ))
    number_match = bool(number and re.search(rf"(?<!\d){re.escape(number)}(?!\d)", refs))
    price_keys = [key for key in props if "price" in key.lower()]
    return {
        "station_id": station["station_id"],
        "poi_name": name,
        "poi_brand": brand,
        "poi_address": props.get("formatted") or props.get("address_line2") or "",
        "poi_city": city,
        "poi_state": props.get("state") or state_code,
        "poi_latitude": lat if lat is not None else "",
        "poi_longitude": lon if lon is not None else "",
        "distance_from_search_anchor_m": round(float(distance), 1) if distance not in (None, "") else "",
        "poi_categories": "|".join(category_list),
        "place_id": props.get("place_id", ""),
        "poi_website": props.get("website") or raw.get("website", ""),
        "poi_reference_fields": "|".join(str(raw.get(key, "")) for key in (
            "ref", "operator:ref", "brand:store", "brand:wikidata",
        ) if raw.get(key)),
        "station_brand_group": station_brand or "",
        "poi_brand_group": poi_brand or "",
        "name_similarity": round(name_score, 3),
        "same_city": same_city,
        "same_state": same_state,
        "fuel_category_confirmed": fuel_type,
        "station_number_found_in_poi_data": number_match,
        "price_like_fields": "|".join(price_keys),
        "_raw_name_score": name_score,
        "_same_city": same_city,
        "_same_state": same_state,
        "_same_brand": bool(station_brand and station_brand == poi_brand),
        "_number_match": number_match,
        "_lat": lat,
        "_lon": lon,
    }


def cluster_count(rows):
    """Count distinct candidate sites, merging duplicate fuel objects within 100 m."""
    sites = []
    for row in rows:
        if row["_lat"] is None or row["_lon"] is None:
            continue
        if not any(haversine_meters(row["_lat"], row["_lon"], item["_lat"], item["_lon"]) <= 100
                   for item in sites):
            sites.append(row)
    return len(sites)


def classify(station, anchor, candidates):
    local = [row for row in candidates if row["fuel_category_confirmed"]
             and row["_same_city"] and row["_same_state"]]
    same_brand = [row for row in local if row["_same_brand"]]
    exact_name = [row for row in local if row["_raw_name_score"] >= 0.88]
    numbered = [row for row in local if row["_number_match"]]
    distinct_brand_sites = cluster_count(same_brand)
    distinct_exact_sites = cluster_count(exact_name)

    def best(rows):
        return max(rows, key=lambda row: (
            row["_number_match"], row["_same_brand"], row["_raw_name_score"],
            row["_same_city"], row["_same_state"],
            -float(row["distance_from_search_anchor_m"] or 1e12),
        ), default=None)

    chosen = best(numbered) if numbered else best(exact_name) if exact_name else best(same_brand)
    anchor_type = (anchor or {}).get("result_type", "")
    precise_anchor = anchor_type in {"amenity", "building"}
    chosen_distance = float(chosen["distance_from_search_anchor_m"] or 1e12) if chosen else 1e12

    if chosen and chosen["_number_match"]:
        status = "station_number_match"
        confidence = "high"
    elif chosen and chosen["_raw_name_score"] >= 0.88 and distinct_exact_sites == 1 and (
        precise_anchor or chosen_distance <= 300
    ):
        status = "exact_name_fuel_poi_match"
        confidence = "high"
    elif chosen and chosen["_same_brand"] and distinct_brand_sites == 1 and precise_anchor:
        status = "unique_brand_near_station_poi"
        confidence = "probable"
    elif same_brand and distinct_brand_sites > 1:
        status = "ambiguous_same_brand_pois"
        confidence = "candidate"
    elif chosen:
        status = "fuel_poi_candidate_identity_unconfirmed"
        confidence = "candidate"
    elif candidates:
        status = "nearby_fuel_pois_different_or_unknown_brand"
        confidence = "unmatched"
    else:
        status = "no_fuel_poi_returned"
        confidence = "unmatched"

    resolved = chosen if confidence in {"high", "probable"} else None
    return {
        "match_status": status,
        "identity_confidence": confidence,
        "resolved_latitude": resolved["poi_latitude"] if resolved else "",
        "resolved_longitude": resolved["poi_longitude"] if resolved else "",
        "selected_poi_name": chosen["poi_name"] if chosen else "",
        "selected_poi_brand": chosen["poi_brand"] if chosen else "",
        "selected_poi_address": chosen["poi_address"] if chosen else "",
        "selected_poi_distance_from_anchor_m": chosen["distance_from_search_anchor_m"] if chosen else "",
        "candidate_poi_count": len(candidates),
        "same_local_city_fuel_poi_count": len(local),
        "same_brand_local_site_count": distinct_brand_sites,
        "exact_name_local_site_count": distinct_exact_sites,
        "station_number_confirmed": bool(chosen and chosen["_number_match"]),
        "search_anchor_type": anchor_type,
        "search_anchor_latitude": (anchor or {}).get("lat", ""),
        "search_anchor_longitude": (anchor or {}).get("lon", ""),
        "search_anchor_address": (anchor or {}).get("formatted", ""),
        "price_api_fields_found": sum(bool(row["price_like_fields"]) for row in candidates),
    }


def submit_batch(session, api_key, addresses):
    response = session.post(
        BATCH_URL,
        params={
            "apiKey": api_key,
            "lang": "en",
            "type": "amenity",
            "countrycodes": "us",
        },
        json=addresses,
        timeout=90,
    )
    if response.status_code != 202:
        raise RuntimeError(f"Geocoding batch submission failed: HTTP {response.status_code}")
    return response.json()["id"]


def retrieve_batch(session, api_key, job_id):
    started = time.monotonic()
    while True:
        response = session.get(
            BATCH_URL,
            params={"id": job_id, "apiKey": api_key, "format": "json"},
            timeout=90,
        )
        if response.status_code == 200:
            return response.json()
        if response.status_code != 202:
            raise RuntimeError(f"Geocoding batch retrieval failed: HTTP {response.status_code}")
        if time.monotonic() - started > MAX_GEOCODE_BATCH_WAIT_SECONDS:
            raise TimeoutError("Geocoding batch is still processing; progress is saved for resume.")
        print("Name-geocoding batch is processing; polling again in 30 seconds.", flush=True)
        time.sleep(30)


def load_batch_geocodes(rows, api_key):
    cached = load_jsonl(BATCH_GEOCODES_FILE)
    missing = [row for row in rows if row["station_id"] not in cached]
    if not missing:
        return cached
    load_dotenv(BASE_DIR / ".env", override=True)
    session = requests.Session()
    state = json.loads(BATCH_STATE_FILE.read_text(encoding="utf-8")) if BATCH_STATE_FILE.exists() else {}
    if state.get("job_id"):
        job_id = state["job_id"]
        print("Resuming saved name-geocoding job.", flush=True)
    else:
        addresses = [
            f"{row['original_name']}, {row['original_city']}, {row['original_state']}, United States"
            for row in missing
        ]
        print(f"Submitting name-geocoding batch for {len(missing)} remaining stations.", flush=True)
        job_id = submit_batch(session, api_key, addresses)
        BATCH_STATE_FILE.write_text(json.dumps({"job_id": job_id, "rows": len(missing)}, indent=2), encoding="utf-8")
        print("Name-geocoding batch submitted.", flush=True)

    results = retrieve_batch(session, api_key, job_id)
    if len(results) != len(missing):
        raise RuntimeError(f"Expected {len(missing)} geocode results, got {len(results)}.")
    for station, result in zip(missing, results):
        record = {"station_id": station["station_id"], "result": result}
        append_jsonl(BATCH_GEOCODES_FILE, record)
        cached[station["station_id"]] = record
    BATCH_STATE_FILE.write_text(json.dumps({"job_id": None, "rows": len(missing), "complete": True}, indent=2), encoding="utf-8")
    return cached


def perform_places(session, api_key, station, anchor):
    if not anchor or anchor.get("lat") is None or anchor.get("lon") is None:
        return None, "no_search_anchor"
    params = {
        "categories": FUEL_CATEGORY,
        "filter": f"circle:{anchor['lon']},{anchor['lat']},{SEARCH_RADIUS_METERS}",
        "bias": f"proximity:{anchor['lon']},{anchor['lat']}",
        "limit": PLACE_LIMIT,
        "lang": "en",
        "apiKey": api_key,
    }
    # Transient TLS/socket timeouts occurred during the larger run. Retry a
    # couple of times with backoff so one flaky connection does not discard a
    # station lookup. Keep 429 handling separate: the caller stops on quota or
    # rate limits instead of retrying and increasing usage.
    for attempt, delay in enumerate((0, 2, 5), start=1):
        if delay:
            time.sleep(delay)
        try:
            response = session.get(PLACES_URL, params=params, timeout=45)
            break
        except requests.RequestException as exc:
            if attempt == 3:
                return None, f"network_error:{type(exc).__name__}"
    if response.status_code == 429:
        return None, "rate_or_quota_limit"
    if not response.ok:
        return None, f"http_{response.status_code}"
    try:
        return response.json(), None
    except ValueError:
        return None, "invalid_json"


def main():
    load_dotenv(BASE_DIR / ".env", override=True)
    api_key = os.getenv("GEOAPIFY_API_KEY")
    if not api_key:
        raise SystemExit("GEOAPIFY_API_KEY is missing from the project .env file.")

    all_rows = read_csv(CANDIDATES_FILE)
    pilot_ids = {row["station_id"] for row in read_csv(PILOT_FILE)}
    stations_by_id = {row["station_id"]: row for row in read_csv(STATIONS_FILE)}
    rows = [row for row in all_rows if row["station_id"] not in pilot_ids]
    if len(rows) != 980:
        raise SystemExit(f"Expected 980 rows outside the 20-row pilot; found {len(rows)}. No API requests sent.")

    batch_records = load_batch_geocodes(rows, api_key)
    cached_places = load_jsonl(API_RESULTS_FILE)
    session = requests.Session()
    station_results = dict(cached_places)
    completed = 0
    failed = 0

    for index, row in enumerate(rows, start=1):
        station_id = row["station_id"]
        cached = station_results.get(station_id)
        if cached and cached.get("request_status") in {"ok", "no_search_anchor"}:
            completed += 1
            continue

        batch_geocode = batch_records.get(station_id, {}).get("result")
        geocode_results = extract_features(batch_geocode)
        selected_geocode = select_geocode_result(geocode_results, row)

        # Prefer a name-resolved station POI. A city or street result is only a
        # search anchor; if the name query did not yield a station-like result,
        # use the saved address-geocoding coordinate.
        selected_name_score = similarity(
            row["original_name"],
            (selected_geocode or {}).get("name") or (selected_geocode or {}).get("formatted", ""),
        )
        selected_is_local = bool(selected_geocode and
                                 norm(selected_geocode.get("city")) == norm(row["original_city"]) and
                                 (norm(selected_geocode.get("state_code")) == norm(row["original_state"])
                                  or norm(selected_geocode.get("state")) == norm(STATE_NAMES.get(row["original_state"], ""))))
        if selected_geocode and selected_geocode.get("lat") is not None and selected_geocode.get("lon") is not None and (
            selected_geocode.get("result_type") in {"amenity", "building"}
            and selected_name_score >= 0.6 and selected_is_local
        ):
            anchor = {
                "lat": selected_geocode["lat"], "lon": selected_geocode["lon"],
                "result_type": selected_geocode.get("result_type", ""),
                "formatted": selected_geocode.get("formatted", ""),
                "anchor_source": "station_name_geocode",
            }
        elif row.get("latitude") and row.get("longitude"):
            anchor = {
                "lat": row["latitude"], "lon": row["longitude"],
                "result_type": row.get("result_type", ""),
                "formatted": row.get("geocoded_address", ""),
                "anchor_source": "saved_address_geocode",
            }
        elif selected_geocode and selected_geocode.get("lat") is not None and selected_geocode.get("lon") is not None and selected_is_local:
            anchor = {
                "lat": selected_geocode["lat"], "lon": selected_geocode["lon"],
                "result_type": selected_geocode.get("result_type", ""),
                "formatted": selected_geocode.get("formatted", ""),
                "anchor_source": "name_query_locality_fallback",
            }
        else:
            anchor = None

        places_data, places_error = perform_places(session, api_key, row, anchor)
        features = (places_data or {}).get("features", [])
        poi_rows = [compact_poi(feature, row, anchor) for feature in features]
        decision = classify(row, anchor, poi_rows)
        request_status = places_error or "ok"
        if places_error == "rate_or_quota_limit":
            # Do not continue spending requests when the provider says to stop.
            record = {
                "station_id": station_id,
                "station_name": row["original_name"],
                "original_address": row["original_address"],
                "original_city": row["original_city"],
                "original_state": row["original_state"],
                "request_status": request_status,
                "message": "Geoapify returned HTTP 429; resume after the daily/rate limit resets.",
            }
            append_jsonl(API_RESULTS_FILE, record)
            station_results[station_id] = record
            print(f"Stopped at {index}/980: provider returned HTTP 429; completed rows are checkpointed.", flush=True)
            break

        record = {
            "station_id": station_id,
            "station_name": row["original_name"],
            "original_address": row["original_address"],
            "original_city": row["original_city"],
            "original_state": row["original_state"],
            "saved_geocode": {
                "latitude": row.get("latitude", ""),
                "longitude": row.get("longitude", ""),
                "formatted": row.get("geocoded_address", ""),
                "result_type": row.get("result_type", ""),
                "confidence": row.get("geocoding_confidence", ""),
                "match_type": row.get("match_type", ""),
            },
            "name_geocode": selected_geocode or {},
            "name_geocode_result_count": len(geocode_results),
            "name_geocode_name_similarity": round(selected_name_score, 3),
            "name_geocode_is_local": selected_is_local,
            "search_anchor": anchor,
            "places_request_status": request_status,
            "request_status": "no_search_anchor" if places_error == "no_search_anchor" else request_status,
            "poi_count": len(poi_rows),
            "poi_candidates": poi_rows,
            **decision,
            "api_price_available": any(row["price_like_fields"] for row in poi_rows),
            "usable_csv_price": "",
            "csv_price_disposition": "withheld_unknown_fuel_grade_and_timestamp",
        }
        append_jsonl(API_RESULTS_FILE, record)
        station_results[station_id] = record
        completed += 1
        if request_status != "ok" and request_status != "no_search_anchor":
            failed += 1
        if index % 25 == 0 or index == len(rows):
            print(f"POI lookups {index}/980; completed rows={completed}; request errors={failed}.", flush=True)
        time.sleep(REQUEST_PAUSE_SECONDS)

    write_outputs(rows, station_results, batch_records)


def write_outputs(rows, station_results, batch_records):
    station_fields = [
        "station_id", "station_name", "original_address", "original_city", "original_state",
        "saved_geocode_latitude", "saved_geocode_longitude", "saved_geocode_result_type",
        "saved_geocode_address", "saved_geocode_confidence", "name_geocode_result_type",
        "name_geocode_name", "name_geocode_address", "name_geocode_latitude",
        "name_geocode_longitude", "name_geocode_confidence", "search_anchor_source",
        "search_anchor_type", "search_anchor_latitude", "search_anchor_longitude",
        "match_status", "identity_confidence", "resolved_latitude", "resolved_longitude",
        "selected_poi_name", "selected_poi_brand", "selected_poi_address",
        "selected_poi_distance_from_anchor_m", "candidate_poi_count",
        "same_local_city_fuel_poi_count", "same_brand_local_site_count",
        "exact_name_local_site_count", "station_number_confirmed", "api_places_request_status",
        "api_price_available", "api_price_value", "api_price_grade", "api_price_timestamp",
        "csv_price_disposition", "usable_price",
    ]
    candidate_fields = [
        "station_id", "station_name", "original_city", "original_state", "poi_name", "poi_brand",
        "poi_address", "poi_city", "poi_state", "poi_latitude", "poi_longitude",
        "distance_from_search_anchor_m", "poi_categories", "place_id", "poi_website",
        "poi_reference_fields", "station_brand_group", "poi_brand_group", "name_similarity",
        "same_city", "same_state", "fuel_category_confirmed", "station_number_found_in_poi_data",
        "price_like_fields",
    ]
    station_outputs, candidate_outputs = [], []
    counts = Counter()
    api_call_count = 0
    price_fields_count = 0
    request_status_counts = Counter()

    for row in rows:
        station_id = row["station_id"]
        record = station_results.get(station_id, {})
        geocode = record.get("name_geocode") or {}
        selected = record
        station_outputs.append({
            "station_id": station_id,
            "station_name": row["original_name"],
            "original_address": row["original_address"],
            "original_city": row["original_city"],
            "original_state": row["original_state"],
            "saved_geocode_latitude": row.get("latitude", ""),
            "saved_geocode_longitude": row.get("longitude", ""),
            "saved_geocode_result_type": row.get("result_type", ""),
            "saved_geocode_address": row.get("geocoded_address", ""),
            "saved_geocode_confidence": row.get("geocoding_confidence", ""),
            "name_geocode_result_type": geocode.get("result_type", ""),
            "name_geocode_name": geocode.get("name", ""),
            "name_geocode_address": geocode.get("formatted", ""),
            "name_geocode_latitude": geocode.get("lat", ""),
            "name_geocode_longitude": geocode.get("lon", ""),
            "name_geocode_confidence": geocode.get("rank", {}).get("confidence", ""),
            "search_anchor_source": (record.get("search_anchor") or {}).get("anchor_source", ""),
            "search_anchor_type": selected.get("search_anchor_type", ""),
            "search_anchor_latitude": selected.get("search_anchor_latitude", ""),
            "search_anchor_longitude": selected.get("search_anchor_longitude", ""),
            "match_status": selected.get("match_status", "not_processed"),
            "identity_confidence": selected.get("identity_confidence", "not_assessed"),
            "resolved_latitude": selected.get("resolved_latitude", ""),
            "resolved_longitude": selected.get("resolved_longitude", ""),
            "selected_poi_name": selected.get("selected_poi_name", ""),
            "selected_poi_brand": selected.get("selected_poi_brand", ""),
            "selected_poi_address": selected.get("selected_poi_address", ""),
            "selected_poi_distance_from_anchor_m": selected.get("selected_poi_distance_from_anchor_m", ""),
            "candidate_poi_count": selected.get("candidate_poi_count", 0),
            "same_local_city_fuel_poi_count": selected.get("same_local_city_fuel_poi_count", 0),
            "same_brand_local_site_count": selected.get("same_brand_local_site_count", 0),
            "exact_name_local_site_count": selected.get("exact_name_local_site_count", 0),
            "station_number_confirmed": selected.get("station_number_confirmed", False),
            "api_places_request_status": selected.get("places_request_status", selected.get("request_status", "not_processed")),
            "api_price_available": selected.get("api_price_available", False),
            "api_price_value": "",
            "api_price_grade": "",
            "api_price_timestamp": "",
            "csv_price_disposition": selected.get("csv_price_disposition", "withheld_unknown_fuel_grade_and_timestamp"),
            "usable_price": "",
        })
        counts[selected.get("match_status", "not_processed")] += 1
        request_status_counts[selected.get("places_request_status", selected.get("request_status", "not_processed"))] += 1
        if selected.get("request_status") in {"ok", "no_search_anchor"}:
            api_call_count += int(bool(selected.get("search_anchor")))
        price_fields_count += int(bool(selected.get("api_price_available")))
        for candidate in selected.get("poi_candidates", []):
            candidate_outputs.append({field: candidate.get(field, "") for field in candidate_fields if field != "original_city" and field != "original_state"})
            candidate_outputs[-1]["original_city"] = row["original_city"]
            candidate_outputs[-1]["original_state"] = row["original_state"]

    with MATCHES_FILE.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=station_fields)
        writer.writeheader()
        writer.writerows(station_outputs)
    with POIS_FILE.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=candidate_fields)
        writer.writeheader()
        writer.writerows(candidate_outputs)

    geocode_count = sum(station_id in batch_records for station_id in (row["station_id"] for row in rows))
    high_confidence_count = sum(counts[status] for status in ("station_number_match", "exact_name_fuel_poi_match"))
    candidate_count = sum(counts[status] for status in ("ambiguous_same_brand_pois", "fuel_poi_candidate_identity_unconfirmed"))
    summary = {
        "input_station_rows": len(rows),
        "pilot_rows_excluded": 20,
        "rows_with_name_geocode_batch_response": geocode_count,
        "places_successful_lookup_rows": api_call_count,
        "places_request_status_counts": dict(request_status_counts),
        "places_request_error_rows": sum(count for status, count in request_status_counts.items()
                                          if status not in {"ok", "no_search_anchor"}),
        "high_confidence_identity_matches": high_confidence_count,
        "high_confidence_identity_match_percent": round(100 * high_confidence_count / len(rows), 1),
        "identity_candidates_requiring_review": candidate_count,
        "identity_candidate_percent": round(100 * candidate_count / len(rows), 1),
        "rows_without_confirmed_station_identity": len(rows) - high_confidence_count,
        "api_price_fields_found_in_fuel_pois": price_fields_count,
        "usable_prices": 0,
        "match_status_counts": dict(counts),
        "places_limit": PLACE_LIMIT,
        "places_radius_meters": SEARCH_RADIUS_METERS,
        "coordinate_policy": "Resolved station coordinates are emitted only for high/probable identity matches; all other POI coordinates remain in the candidate file for review.",
        "price_policy": "Geoapify fuel POIs provide location/category data, not a grade-and-timestamp price feed. CSV average prices are withheld from usable_price until fuel grade and timestamp are known.",
        "outputs": [str(MATCHES_FILE.relative_to(BASE_DIR)), str(POIS_FILE.relative_to(BASE_DIR)), str(API_RESULTS_FILE.relative_to(BASE_DIR))],
    }
    SUMMARY_FILE.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    main()
