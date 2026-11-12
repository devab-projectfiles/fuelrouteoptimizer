"""Audit the first 1,000 geocoder results without making API calls.

This report distinguishes a coordinate returned by a geocoder from a
station-level coordinate verified against an independent POI source.
"""

import csv
import json
from collections import Counter
from math import asin, cos, radians, sin, sqrt
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]
INPUT_FILE = BASE_DIR / "data" / "geocoded_station_candidates.csv"
VERIFIED_FILE = BASE_DIR / "data" / "verified_station_coordinates.csv"
AUDIT_FILE = BASE_DIR / "data" / "geocoding_reliability_audit.csv"
SUMMARY_FILE = BASE_DIR / "data" / "geocoding_reliability_summary.json"
MATCH_RADIUS_METERS = 250


def distance_meters(lat1, lon1, lat2, lon2):
    earth_radius = 6_371_000
    lat1, lon1, lat2, lon2 = map(radians, map(float, (lat1, lon1, lat2, lon2)))
    delta_lat = lat2 - lat1
    delta_lon = lon2 - lon1
    value = sin(delta_lat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(delta_lon / 2) ** 2
    return 2 * earth_radius * asin(sqrt(value))


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def main():
    rows = read_csv(INPUT_FILE)
    verified = {row["station_id"]: row for row in read_csv(VERIFIED_FILE)}
    output_fields = [
        "station_id", "station_name", "input_address", "city", "state",
        "geocoded_address", "geocoder_result_type", "geocoder_confidence",
        "geocoder_coordinate_status", "independent_station_coordinate",
        "independent_latitude", "independent_longitude", "independent_source",
        "distance_to_verified_m", "audit_class", "audit_reason",
    ]
    counts = Counter()

    with AUDIT_FILE.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=output_fields)
        writer.writeheader()
        for row in rows:
            ref = verified.get(row["station_id"])
            lat, lon = row.get("latitude"), row.get("longitude")
            dist = None
            if ref and lat and lon:
                dist = distance_meters(lat, lon, ref["latitude"], ref["longitude"])

            if ref:
                counts["independently_verified_station_records"] += 1
                if not lat or not lon:
                    audit_class = "verified_location_geocoder_missing"
                    reason = "Independent station coordinate is available; geocoder returned no coordinate."
                elif dist is not None and dist <= MATCH_RADIUS_METERS:
                    audit_class = "verified_coordinate_agrees"
                    reason = "Independent station coordinate agrees within 250 m."
                else:
                    audit_class = "verified_coordinate_conflict"
                    reason = "Independent station coordinate exists; geocoder point does not agree within 250 m."
            elif not lat or not lon:
                audit_class = "no_coordinate"
                reason = "Geocoder returned no usable coordinate; no independent station coordinate is available."
            elif row.get("result_type") in {"city", "suburb", "county", "state"}:
                audit_class = "locality_only"
                reason = "Coordinate represents a locality or administrative area, not a station."
            elif row.get("result_type") == "street":
                audit_class = "street_only"
                reason = "Coordinate represents a street or road reference, not a station."
            else:
                audit_class = "unverified_poi_candidate"
                reason = "Geocoder result is a POI/building candidate but has no independent fuel-station confirmation."

            counts[audit_class] += 1
            writer.writerow({
                "station_id": row["station_id"],
                "station_name": row["original_name"],
                "input_address": row["original_address"],
                "city": row["original_city"],
                "state": row["original_state"],
                "geocoded_address": row["geocoded_address"],
                "geocoder_result_type": row["result_type"],
                "geocoder_confidence": row["geocoding_confidence"],
                "geocoder_coordinate_status": row["coordinate_status"],
                "independent_station_coordinate": "yes" if ref else "no",
                "independent_latitude": ref["latitude"] if ref else "",
                "independent_longitude": ref["longitude"] if ref else "",
                "independent_source": ref["source"] if ref else "",
                "distance_to_verified_m": round(dist, 1) if dist is not None else "",
                "audit_class": audit_class,
                "audit_reason": reason,
            })

    total = len(rows)
    summary = {
        "input_file": str(INPUT_FILE.relative_to(BASE_DIR)),
        "audited_rows": total,
        "definition": "Reliable means an independent station coordinate agrees within 250 m; a geocoder confidence score alone is not verification.",
        "independent_verified_count": counts["independently_verified_station_records"],
        "independent_verified_percent": round(100 * counts["independently_verified_station_records"] / total, 2) if total else 0,
        "geocoder_agrees_with_independent_count": counts["verified_coordinate_agrees"],
        "geocoder_agreement_percent": round(100 * counts["verified_coordinate_agrees"] / total, 2) if total else 0,
        "classes": {name: counts[name] for name in (
            "verified_coordinate_agrees", "verified_coordinate_conflict",
            "verified_location_geocoder_missing", "street_only", "locality_only",
            "unverified_poi_candidate", "no_coordinate",
        )},
        "geocoder_status_counts": dict(Counter(row.get("coordinate_status", "") for row in rows)),
        "result_type_counts": dict(Counter(row.get("result_type", "") or "not_found" for row in rows)),
        "note": "This is an evidence audit, not a claim that all unmatched locations are wrong. The current files do not include independent POI coverage for the 1,000-row batch.",
    }
    SUMMARY_FILE.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    print(f"Detailed audit: {AUDIT_FILE}")


if __name__ == "__main__":
    main()
