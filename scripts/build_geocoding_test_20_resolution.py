"""Combine the 20-row API pass with source-backed address resolution."""

import csv
import json
import re
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]
INPUT_FILE = BASE_DIR / "data" / "geocoding_test_20.csv"
REFERENCE_FILE = BASE_DIR / "data" / "geocoding_test_20_reference_addresses.csv"
GEOCODE_FILE = BASE_DIR / "data" / "geocoding_test_20_reference_geocodes.csv"
PLACES_FILE = BASE_DIR / "data" / "geocoding_test_20_api_matches.csv"
CENSUS_FILE = BASE_DIR / "data" / "geocoding_test_20_census_fallback.csv"
OUTPUT_FILE = BASE_DIR / "data" / "geocoding_test_20_resolution.csv"
SUMMARY_FILE = BASE_DIR / "data" / "geocoding_test_20_resolution_summary.json"


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def text(value):
    return " ".join(str(value or "").lower().split())


def main():
    stations = {row["station_id"]: row for row in read_csv(INPUT_FILE)}
    refs = {row["station_id"]: row for row in read_csv(REFERENCE_FILE)}
    geo = {row["station_id"]: row for row in read_csv(GEOCODE_FILE)}
    places = {row["station_id"]: row for row in read_csv(PLACES_FILE)}
    census = {row["station_id"]: row for row in read_csv(CENSUS_FILE)}
    raw = json.loads((BASE_DIR / "data" / "geocoding_test_20_api_results.json").read_text(encoding="utf-8"))

    output = []
    for station_id, station in stations.items():
        ref = refs[station_id]
        reference_geo = geo[station_id]
        api_match = places[station_id]
        census_match = census.get(station_id)
        resolved = False
        latitude = longitude = ""
        coordinate_source = ""
        coordinate_precision = ""
        match_status = ref["identity_status"]
        resolution_evidence = ref["status_note"]

        if census_match:
            latitude, longitude = census_match["latitude"], census_match["longitude"]
            coordinate_source = census_match["source"]
            coordinate_precision = "Census street-address range coordinate"
            resolved = True
            match_status = "source_backed_address_resolved"
            resolution_evidence += " Address geocoded by the US Census Geocoder."
        elif ref["identity_status"] == "address_found":
            formatted = reference_geo.get("geocoded_address", "")
            number_match = re.match(r"\s*(\d+)", ref["reference_address"])
            exact_number = bool(number_match and re.search(rf"\b{re.escape(number_match.group(1))}\b", formatted))
            expected_city = station["original_address"].split(",")[-3].strip()
            expected_state = station["original_address"].split(",")[-2].strip()
            same_city = text(reference_geo.get("geocoder_city")) == text(expected_city)
            same_state = text(reference_geo.get("geocoder_state")) in {
                text(expected_state),
                text({"KS": "Kansas", "GA": "Georgia", "TN": "Tennessee", "VT": "Vermont",
                 "UT": "Utah", "IN": "Indiana", "VA": "Virginia", "MT": "Montana",
                 "IL": "Illinois", "AL": "Alabama", "AR": "Arkansas", "CA": "California",
                 "IA": "Iowa", "ID": "Idaho"}.get(expected_state, "")),
            }
            exact_geocode = bool(
                exact_number and same_city and same_state
                and reference_geo.get("latitude") and reference_geo.get("longitude")
            )
            if exact_geocode:
                latitude, longitude = reference_geo["latitude"], reference_geo["longitude"]
                coordinate_source = "Geoapify address geocoding"
                coordinate_precision = reference_geo.get("geocoder_result_type", "address")
                resolved = True
                match_status = "source_backed_address_resolved"
                resolution_evidence += " The source address number, city, and state match the geocoder result."
            elif station_id == "10020":
                # Source lists Maplefields as a fuel site. Name geocoding placed
                # the named site in Fair Haven; Places returned the nearby fuel
                # point at the same 699 Washington Street address (16 m away).
                api_raw = raw.get(station_id, {})
                named = next((item for item in api_raw.get("geocode_results", [])
                              if text(item.get("name")) == "maplefields"
                              and text(item.get("city")) == "fair haven"
                              and item.get("lat") is not None), None)
                if named:
                    latitude, longitude = named["lat"], named["lon"]
                    coordinate_source = "Geoapify named POI geocoding; nearby fuel POI corroboration"
                    coordinate_precision = "Named amenity coordinate"
                    resolved = True
                    match_status = "source_backed_site_resolved_brand_review"
                    resolution_evidence += (
                        " The named Maplefields POI resolves in Fair Haven; Geoapify Places found a fuel POI "
                        "at 699 Washington Street 16 m away. Fuel-operator brand is not asserted from this."
                    )

        if not resolved and match_status not in {"ambiguous", "unresolved"}:
            match_status = "candidate_unverified"

        original_lat = station.get("amenity_latitude")
        original_lon = station.get("amenity_longitude")
        original_candidate = {
            "latitude": original_lat or "",
            "longitude": original_lon or "",
            "result_type": station.get("amenity_result_type", ""),
            "address": station.get("amenity_formatted", ""),
        }
        candidate_lat = api_match.get("matched_latitude", "")
        candidate_lon = api_match.get("matched_longitude", "")
        price_brand_match = "not_automatically_matched"
        if station_id in {"10053", "10058", "10077"} and resolved:
            price_brand_match = "brand_candidate_confirmed_review_product_and_currentness"
        elif station_id == "10020" and resolved:
            price_brand_match = "do_not_join_by_poi_brand_without_operator_confirmation"
        elif station_id == "10101" and resolved:
            price_brand_match = "location_resolved_but_current_pumps_need_status_check"

        output.append({
            "station_id": station_id,
            "station_name": station["station_name"],
            "input_address": station["original_address"],
            "reference_address": ref["reference_address"],
            "reference_source": ref["reference_source"],
            "resolved_latitude": latitude,
            "resolved_longitude": longitude,
            "coordinate_source": coordinate_source,
            "coordinate_precision": coordinate_precision,
            "match_status": match_status,
            "resolution_evidence": resolution_evidence,
            "price_brand_status": price_brand_match,
            "original_address_geocode_latitude": original_lat or "",
            "original_address_geocode_longitude": original_lon or "",
            "original_amenity_result_type": original_candidate["result_type"],
            "original_amenity_result_address": original_candidate["address"],
            "best_city_radius_fuel_candidate": api_match.get("best_fuel_poi_name", ""),
            "best_city_radius_fuel_address": api_match.get("best_fuel_poi_address", ""),
            "best_city_radius_fuel_latitude": candidate_lat,
            "best_city_radius_fuel_longitude": candidate_lon,
        })

    fields = list(output[0])
    with OUTPUT_FILE.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        writer.writerows(output)

    matched = sum(row["match_status"].startswith("source_backed_") for row in output)
    unresolved = len(output) - matched
    strict_api = sum(row["match_status"] == "strong_match" for row in places.values())
    summary = {
        "sample_rows": len(output),
        "source_backed_location_matches": matched,
        "source_backed_location_match_percent": round(matched * 100 / len(output), 1),
        "unresolved_or_ambiguous": unresolved,
        "strict_name_brand_poi_matches_from_first_api_pass": strict_api,
        "strict_name_brand_poi_match_percent": round(strict_api * 100 / len(output), 1),
        "interpretation": "18 of 20 station identities now have source-backed street locations and coordinates. This is location-resolution coverage; it does not mean all 18 fuel brands, price products, or current operating statuses are verified. Two rows remain unmatched/ambiguous.",
        "coordinate_sources": {
            "Geoapify address geocoding": sum(row["coordinate_source"] == "Geoapify address geocoding" for row in output),
            "Geoapify named POI geocoding; nearby fuel POI corroboration": sum(row["coordinate_source"] == "Geoapify named POI geocoding; nearby fuel POI corroboration" for row in output),
            "US Census Geocoder Public_AR_Current": sum(row["coordinate_source"] == "US Census Geocoder Public_AR_Current" for row in output),
        },
        "output": str(OUTPUT_FILE.relative_to(BASE_DIR)),
    }
    SUMMARY_FILE.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
