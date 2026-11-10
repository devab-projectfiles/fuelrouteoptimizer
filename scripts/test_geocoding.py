import csv
import json
from pathlib import Path

from fuel_optimizer.services.station_matching_service import (
    normalize_text,
    similarity,
)

# ============================================================
# CONFIGURATION
# ============================================================

BASE_DIR = Path(__file__).resolve().parents[1]

INPUT_FILE = BASE_DIR / "data" / "geocoding_test_20.csv"

PLACES_RESULTS_FILE = BASE_DIR / "data" / "geocoding_test_places_results.json"

OUTPUT_FILE = BASE_DIR / "data" / "geocoding_test_places_verification.csv"

BRAND_ALIASES = {
    "loves": {"loves", "love s"},
    "pilot": {"pilot"},
    "pilot flying j": {"pilot flying j"},
    "circle k": {"circle k"},
    "citgo": {"citgo"},
    "shell": {"shell"},
    "conoco": {"conoco"},
    "bp": {"bp"},
    "chevron": {"chevron"},
    "exxon": {"exxon"},
    "exxonmobil": {"exxonmobil"},
    "mobil": {"mobil"},
    "murphy express": {"murphy express", "murphy usa"},
    "maplefields": {"maplefields"},
}

GENERIC_NAME_TERMS = {
    "travel", "stop", "stops", "center", "centers", "plaza", "truck",
    "fuel", "mart", "food", "store", "stores", "convenience", "gas",
    "station", "dba", "the",
}

STRONG_DISTANCE_METERS = 250


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


def canonical_brand(name):
    """Return a known brand only when its alias appears as whole words."""
    words = normalize_text(name).split()
    # Strip store numbers and generic descriptors before alias matching.
    compact = " ".join(
        word for word in words
        if not word.isdigit() and word not in GENERIC_NAME_TERMS
    )
    for brand, aliases in BRAND_ALIASES.items():
        for alias in aliases:
            alias_text = normalize_text(alias)
            alias_words = alias_text.split()
            if (len(alias_words) == 1 and alias_words[0] in words) or alias_text == compact:
                return brand
    return None


def classify_cached_poi(station_name, poi):
    station_brand = canonical_brand(station_name)
    poi_brand = canonical_brand(poi.get("name", ""))
    distance = float(poi.get("distance_meters", 0))
    score = similarity(station_name, poi.get("name", ""))
    if station_brand and station_brand == poi_brand:
            status = (
                "candidate_brand_match_within_250m"
                if distance <= STRONG_DISTANCE_METERS
                else "candidate_brand_match_over_250m"
            )
    elif not poi.get("name"):
        status = "unnamed_fuel_poi"
    else:
        status = "different_or_unknown_brand"
    return station_brand, poi_brand, round(score, 3), status


# ============================================================
# SAVE CSV REPORT
# ============================================================


def save_csv_report(stations, saved_results):

    fields = [
        "station_id",
        "station_name",
        "original_address",
        "amenity_result_type",
        "candidate_latitude",
        "candidate_longitude",
        "fuel_poi_count",
        "poi_name",
        "poi_address",
        "poi_latitude",
        "poi_longitude",
        "name_similarity",
        "station_brand",
        "poi_brand",
        "review_status",
        "distance_meters",
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

            pois = result.get("pois", [])
            ranked = []
            for poi in pois:
                station_brand, poi_brand, score, status = classify_cached_poi(
                    station["station_name"], poi
                )
                ranked.append((status, float(poi.get("distance_meters", 0)), poi,
                               station_brand, poi_brand, score))
            ranked.sort(key=lambda row: (
                row[0] not in {
                    "candidate_brand_match_within_250m",
                    "candidate_brand_match_over_250m",
                },
                row[1],
            ))
            if not ranked:
                ranked = [("no_cached_poi", "", {}, canonical_brand(station["station_name"]), None, "")]
            for status, _, poi, station_brand, poi_brand, score in ranked:
                writer.writerow({
                    "station_id": station["station_id"],
                    "station_name": station["station_name"],
                    "original_address": station.get("original_address"),
                    "amenity_result_type": station.get("amenity_result_type"),
                    "candidate_latitude": candidate.get("latitude") or station.get("amenity_latitude"),
                    "candidate_longitude": candidate.get("longitude") or station.get("amenity_longitude"),
                    "fuel_poi_count": len(pois),
                    "poi_name": poi.get("name"),
                    "poi_address": poi.get("address"),
                    "poi_latitude": poi.get("latitude"),
                    "poi_longitude": poi.get("longitude"),
                    "name_similarity": score,
                    "station_brand": station_brand,
                    "poi_brand": poi_brand,
                    "review_status": status,
                    "distance_meters": poi.get("distance_meters"),
                })


# ============================================================
# MAIN
# ============================================================


def main():
    stations = load_comparison_results()

    if not stations:

        raise RuntimeError("No geocoding comparison results found.")

    saved_results = load_saved_results()

    if not saved_results:
        raise RuntimeError("No cached Places results found; offline review needs the saved JSON.")

    print("\nOFFLINE FUEL STATION POI REVIEW")
    print("===============================")
    print("Stations:", len(stations))
    print("Cached station records:", len(saved_results))
    print("API requests: 0 (this script is offline-only)")

    save_csv_report(
        stations,
        saved_results,
    )

    print("CSV report:", OUTPUT_FILE)


if __name__ == "__main__":

    main()
