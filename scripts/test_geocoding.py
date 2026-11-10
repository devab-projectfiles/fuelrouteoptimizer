import csv
import json
import os
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

from fuel_optimizer.services.station_matching_service import (
    normalize_text,
    similarity,
    calculate_distance_meters,
)

# ============================================================
# CONFIGURATION
# ============================================================

BASE_DIR = Path(__file__).resolve().parents[1]

load_dotenv(BASE_DIR / ".env", override=True)

API_KEY = os.getenv("GEOAPIFY_API_KEY")

INPUT_FILE = BASE_DIR / "data" / "geocoding_test_20.csv"

PLACES_RESULTS_FILE = BASE_DIR / "data" / "geocoding_test_places_results.json"

OUTPUT_FILE = BASE_DIR / "data" / "geocoding_test_places_verification.csv"

PLACES_URL = "https://api.geoapify.com/v2/places"

SEARCH_RADIUS_METERS = 1000

MAX_RESULTS = 100

REQUEST_DELAY_SECONDS = 0.5

# Matching thresholds
STRONG_NAME_SIMILARITY = 0.80
POSSIBLE_NAME_SIMILARITY = 0.50

STRONG_DISTANCE_METERS = 250
POSSIBLE_DISTANCE_METERS = 1000


# ============================================================
# FILE HELPERS
# ============================================================


def load_comparison_results():

    with INPUT_FILE.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as file:

        return list(csv.DictReader(file))


def load_saved_results():

    if not PLACES_RESULTS_FILE.exists():
        return {}

    with PLACES_RESULTS_FILE.open(
        "r",
        encoding="utf-8",
    ) as file:

        return json.load(file)


def save_results(results):

    with PLACES_RESULTS_FILE.open(
        "w",
        encoding="utf-8",
    ) as file:

        json.dump(
            results,
            file,
            indent=4,
        )


# ============================================================
# COORDINATE HELPERS
# ============================================================


def get_candidate_coordinates(station):
    """
    Prefer the station-name + address geocoding result.

    Do not use city-level address coordinates as a fuel
    station location.
    """

    latitude = station.get("amenity_latitude")
    longitude = station.get("amenity_longitude")

    result_type = station.get("amenity_result_type")

    if not latitude or not longitude:
        return None

    try:

        latitude = float(latitude)
        longitude = float(longitude)

    except (TypeError, ValueError):
        return None

    if not -90 <= latitude <= 90:
        return None

    if not -180 <= longitude <= 180:
        return None

    return {
        "latitude": latitude,
        "longitude": longitude,
        "result_type": result_type,
    }


# ============================================================
# GEOAPIFY PLACES API
# ============================================================


def find_nearby_fuel_stations(latitude, longitude):
    """
    Search actual fuel-station POIs around a geocoded
    candidate using Geoapify Places API.
    """

    payload = {
        "categories": ["service.vehicle.fuel"],
        "filter": {
            "type": "circle",
            "lon": longitude,
            "lat": latitude,
            "radius": SEARCH_RADIUS_METERS,
        },
        "bias": {
            "type": "proximity",
            "lon": longitude,
            "lat": latitude,
        },
        "limit": MAX_RESULTS,
        "offset": 0,
    }

    try:

        response = requests.post(
            PLACES_URL,
            params={
                "apiKey": API_KEY,
            },
            json=payload,
            timeout=30,
        )

    except requests.RequestException:

        raise RuntimeError(
            "Places API request failed. Check your internet connection."
        ) from None

    if not response.ok:

        raise RuntimeError(
            f"Places API returned HTTP {response.status_code}: "
            f"{response.text[:500]}"
        )

    return response.json()


# ============================================================
# POI NORMALIZATION
# ============================================================


def normalize_poi(feature, candidate):

    properties = feature.get("properties", {})

    geometry = feature.get("geometry", {})

    coordinates = geometry.get("coordinates", [])

    if len(coordinates) < 2:
        return None

    longitude = coordinates[0]
    latitude = coordinates[1]

    name = properties.get("name") or ""

    address = properties.get("formatted") or ""

    categories = properties.get("categories") or []

    distance = calculate_distance_meters(
        candidate["latitude"],
        candidate["longitude"],
        latitude,
        longitude,
    )

    return {
        "name": name,
        "address": address,
        "city": properties.get("city"),
        "state": properties.get("state"),
        "latitude": latitude,
        "longitude": longitude,
        "distance_meters": round(distance, 2),
        "categories": categories,
        "place_id": properties.get("place_id"),
    }


# ============================================================
# MATCHING
# ============================================================


def classify_station(station, candidate, pois):

    original_name = station.get("station_name", "")

    if not pois:

        return {
            "status": "no_fuel_poi_found",
            "reason": "No fuel POIs found within search radius.",
            "best_match": None,
        }

    matches = []

    for poi in pois:

        name_score = similarity(
            original_name,
            poi["name"],
        )

        distance = poi["distance_meters"]

        matches.append(
            {
                **poi,
                "name_similarity": round(name_score, 3),
            }
        )

    matches.sort(
        key=lambda item: (
            item["name_similarity"],
            -item["distance_meters"],
        ),
        reverse=True,
    )

    best_match = matches[0]

    name_score = best_match["name_similarity"]

    distance = best_match["distance_meters"]

    if name_score >= STRONG_NAME_SIMILARITY and distance <= STRONG_DISTANCE_METERS:

        return {
            "status": "strong_match",
            "reason": (
                "Station name similarity is high "
                "and the fuel POI is within 250 meters."
            ),
            "best_match": best_match,
        }

    if name_score >= POSSIBLE_NAME_SIMILARITY and distance <= POSSIBLE_DISTANCE_METERS:

        return {
            "status": "possible_match",
            "reason": (
                "Potential station-name match. " "Independent verification is required."
            ),
            "best_match": best_match,
        }

    return {
        "status": "fuel_poi_name_mismatch",
        "reason": (
            "Fuel POIs were found, but their names "
            "do not sufficiently match the CSV station."
        ),
        "best_match": best_match,
    }


# ============================================================
# PROCESS ONE STATION
# ============================================================


def process_station(station):

    station_id = station["station_id"]

    print(f"\nProcessing station {station_id}: " f"{station['station_name']}")

    candidate = get_candidate_coordinates(station)

    if candidate is None:

        print("No usable amenity coordinates. Skipping API request.")

        return {
            "station_id": station_id,
            "status": "no_geocoding_coordinates",
            "reason": (
                "The name + address geocoding result "
                "did not contain usable coordinates."
            ),
            "pois": [],
            "best_match": None,
        }

    print(
        "Geocoding candidate:",
        candidate["latitude"],
        candidate["longitude"],
    )

    print(
        "Candidate result type:",
        candidate["result_type"],
    )

    print(f"Searching within {SEARCH_RADIUS_METERS} meters...")

    data = find_nearby_fuel_stations(
        candidate["latitude"],
        candidate["longitude"],
    )

    features = data.get("features", [])

    pois = []

    for feature in features:

        poi = normalize_poi(
            feature,
            candidate,
        )

        if poi is not None:
            pois.append(poi)

    pois.sort(key=lambda item: item["distance_meters"])

    classification = classify_station(
        station,
        candidate,
        pois,
    )

    print("Fuel POIs found:", len(pois))

    print("Classification:", classification["status"])

    if classification["best_match"]:

        best = classification["best_match"]

        print("Best POI:", best["name"])

        print(
            "Name similarity:",
            best["name_similarity"],
        )

        print(
            "Distance:",
            best["distance_meters"],
            "meters",
        )

    return {
        "station_id": station_id,
        "station_name": station["station_name"],
        "candidate": candidate,
        "status": classification["status"],
        "reason": classification["reason"],
        "best_match": classification["best_match"],
        "pois": pois,
    }


# ============================================================
# SAVE CSV REPORT
# ============================================================


def save_csv_report(stations, saved_results):

    fields = [
        "station_id",
        "station_name",
        "amenity_result_type",
        "candidate_latitude",
        "candidate_longitude",
        "status",
        "fuel_poi_count",
        "matched_poi_name",
        "matched_poi_address",
        "matched_poi_latitude",
        "matched_poi_longitude",
        "name_similarity",
        "distance_meters",
        "reason",
    ]

    with OUTPUT_FILE.open(
        "w",
        encoding="utf-8",
        newline="",
    ) as file:

        writer = csv.DictWriter(
            file,
            fieldnames=fields,
        )

        writer.writeheader()

        for station in stations:

            result = saved_results.get(
                station["station_id"],
                {},
            )

            candidate = result.get("candidate") or {}

            best = result.get("best_match") or {}

            writer.writerow(
                {
                    "station_id": station["station_id"],
                    "station_name": station["station_name"],
                    "amenity_result_type": station["amenity_result_type"],
                    "candidate_latitude": candidate.get("latitude"),
                    "candidate_longitude": candidate.get("longitude"),
                    "status": result.get("status"),
                    "fuel_poi_count": len(result.get("pois", [])),
                    "matched_poi_name": best.get("name"),
                    "matched_poi_address": best.get("address"),
                    "matched_poi_latitude": best.get("latitude"),
                    "matched_poi_longitude": best.get("longitude"),
                    "name_similarity": best.get("name_similarity"),
                    "distance_meters": best.get("distance_meters"),
                    "reason": result.get("reason"),
                }
            )


# ============================================================
# MAIN
# ============================================================


def main():

    if not API_KEY:

        raise RuntimeError("GEOAPIFY_API_KEY is missing from .env")

    stations = load_comparison_results()

    if not stations:

        raise RuntimeError("No geocoding comparison results found.")

    saved_results = load_saved_results()

    print("\nFUEL STATION POI VERIFICATION")

    print("=============================")

    print("Stations:", len(stations))

    print("Previously saved results:", len(saved_results))

    requests_made = 0

    for station in stations:

        station_id = station["station_id"]

        # Resume without repeating successful requests.
        if station_id in saved_results:

            print(f"\nSkipping {station_id}: " "saved results already exist.")

            continue

        result = process_station(station)

        saved_results[station_id] = result

        # Save after every station so interruptions
        # do not lose completed work.
        save_results(saved_results)

        if result.get("candidate"):

            requests_made += 1

            time.sleep(REQUEST_DELAY_SECONDS)

    save_csv_report(
        stations,
        saved_results,
    )

    print("\nEXPERIMENT COMPLETED")

    print("====================")

    print("Stations:", len(stations))

    print("New API requests:", requests_made)

    print("JSON results:", PLACES_RESULTS_FILE)

    print("CSV report:", OUTPUT_FILE)

    print("\nCLASSIFICATION SUMMARY")

    from collections import Counter

    counts = Counter(result.get("status") for result in saved_results.values())

    for status, count in counts.items():

        print(f"{status}: {count}")


if __name__ == "__main__":

    main()
