import re
from difflib import SequenceMatcher
from math import asin, cos, radians, sin, sqrt

MAX_MATCH_DISTANCE_METERS = 250
MIN_NAME_SIMILARITY = 0.80


def normalize_text(value):
    if not value:
        return ""

    value = str(value).lower()
    value = re.sub(r"[^a-z0-9\s]", " ", value)

    return " ".join(value.split())


GENERIC_NAME_TERMS = {
    "travel", "stop", "stops", "center", "centers", "plaza", "truck",
    "fuel", "mart", "food", "store", "stores", "convenience", "gas",
    "station", "dba", "the",
}

BRAND_ALIASES = {
    "love s": "loves",
    "pilot flying j": "pilot flying j",
    "pilot": "pilot",
    "flying j": "flying j",
    "circle k": "circle k",
    "citgo": "citgo",
    "kwik trip": "kwik trip",
    "shell": "shell",
    "conoco": "conoco",
    "chevron": "chevron",
    "exxonmobil": "exxonmobil",
    "exxon": "exxon",
    "mobil": "mobil",
    "bp": "bp",
}


def normalize_station_name(value):
    """Normalize a trading name while ignoring store numbers and descriptors."""
    words = normalize_text(value).split()
    words = [word for word in words if not word.isdigit() and word not in GENERIC_NAME_TERMS]
    return " ".join(words)


def canonical_brand(value):
    """Identify a supported brand from the cleaned station name."""
    cleaned = normalize_station_name(value)
    if cleaned in BRAND_ALIASES:
        return BRAND_ALIASES[cleaned]
    # Some CSV names include a brand plus a local descriptor. Match aliases
    # only as complete word sequences, never by arbitrary substring.
    for alias in sorted(BRAND_ALIASES, key=len, reverse=True):
        if f" {alias} " in f" {cleaned} ":
            return BRAND_ALIASES[alias]
    return None


def similarity(first, second):
    first = normalize_station_name(first)
    second = normalize_station_name(second)

    first_brand = canonical_brand(first)
    second_brand = canonical_brand(second)

    if first_brand and first_brand == second_brand:
        return 1.0

    if not first or not second:
        return 0.0

    return SequenceMatcher(None, first, second).ratio()


def calculate_distance_meters(lat1, lon1, lat2, lon2):
    earth_radius_meters = 6371000

    lat1 = radians(float(lat1))
    lon1 = radians(float(lon1))
    lat2 = radians(float(lat2))
    lon2 = radians(float(lon2))

    delta_lat = lat2 - lat1
    delta_lon = lon2 - lon1

    a = sin(delta_lat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(delta_lon / 2) ** 2

    return 2 * earth_radius_meters * asin(sqrt(a))


def address_matches(geo_address, verified_address):
    geo_address = normalize_text(geo_address)
    verified_address = normalize_text(verified_address)

    if not geo_address or not verified_address:
        return False

    return verified_address in geo_address


def match_station(geo_station, csv_stations):
    geo_name = normalize_text(geo_station.get("name"))
    geo_address = geo_station.get("address", "")

    if not geo_name:
        return {
            "status": "unmatched",
            "reason": "The fuel POI has no name; no CSV identity can be established.",
            "station": None,
        }

    if geo_station.get("latitude") is None or geo_station.get("longitude") is None:
        return {
            "status": "unmatched",
            "reason": "The fuel POI has no usable coordinates.",
            "station": None,
        }

    candidates = []

    for station in csv_stations:
        station_name = station.get("name", "")
        station_address = station.get("verified_address")

        name_score = similarity(geo_name, station_name)

        if name_score < MIN_NAME_SIMILARITY:
            continue

        # Coordinates must have been independently verified.
        if station.get("latitude") is None or station.get("longitude") is None:
            continue

        # Require the Geoapify address to contain the
        # independently verified street address.
        if not address_matches(geo_address, station_address):
            continue

        distance = calculate_distance_meters(
            geo_station["latitude"],
            geo_station["longitude"],
            station["latitude"],
            station["longitude"],
        )

        candidates.append(
            {
                "station": station,
                "name_score": round(name_score, 3),
                "distance_meters": round(distance, 2),
            }
        )

    nearby_candidates = [
        candidate
        for candidate in candidates
        if candidate["distance_meters"] <= MAX_MATCH_DISTANCE_METERS
    ]

    if len(nearby_candidates) == 1:
        candidate = nearby_candidates[0]

        return {
            "status": "probable_match",
            "reason": (
                "Station name, verified address, " "and geographic distance agree"
            ),
            **candidate,
        }

    if len(nearby_candidates) > 1:
        return {
            "status": "ambiguous",
            "reason": "Multiple stations satisfy matching criteria",
            "candidates": nearby_candidates,
        }

    return {
        "status": "unmatched",
        "reason": "No independently verified CSV station satisfied the name, address, and distance requirements.",
        "station": None,
    }
