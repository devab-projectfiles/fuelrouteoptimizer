import os
from pathlib import Path

import requests
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parents[2]
load_dotenv(BASE_DIR / ".env")

GEOAPIFY_API_KEY = os.getenv("GEOAPIFY_API_KEY")

PLACES_URL = "https://api.geoapify.com/v2/places"


class FuelStationError(Exception):
    """Raised when fuel station discovery fails."""


def find_fuel_stations(route_coordinates, buffer_meters=5000):
    """
    Find fuel stations within a corridor around a route.

    Args:
        route_coordinates: List of [longitude, latitude] positions.
        buffer_meters: Search distance from the route in meters.

    Returns:
        List of normalized fuel station dictionaries.
    """

    if not GEOAPIFY_API_KEY:
        raise FuelStationError("GEOAPIFY_API_KEY is missing.")

    if len(route_coordinates) < 2:
        raise ValueError("A route must contain at least two coordinates.")

    if not 0 < buffer_meters <= 100000:
        raise ValueError("Buffer must be between 0 and 100000 meters.")

    for coordinate in route_coordinates:
        if len(coordinate) != 2:
            raise ValueError("Each coordinate must contain longitude and latitude.")

        longitude, latitude = coordinate

        if not -180 <= longitude <= 180:
            raise ValueError("Invalid longitude.")

        if not -90 <= latitude <= 90:
            raise ValueError("Invalid latitude.")

    payload = {
        "categories": ["service.vehicle.fuel"],
        "filter": {
            "type": "polyline",
            "geometry": {
                "type": "LineString",
                "coordinates": route_coordinates,
            },
            "buffer": buffer_meters,
        },
        "limit": 100,
        "offset": 0,
    }

    try:
        response = requests.post(
            PLACES_URL,
            params={"apiKey": GEOAPIFY_API_KEY},
            json=payload,
            timeout=30,
        )

        response.raise_for_status()
        data = response.json()

    except requests.RequestException as exc:
        raise FuelStationError(f"Fuel station search failed: {exc}") from exc

    features = data.get("features", [])

    stations = []

    for feature in features:
        properties = feature.get("properties", {})
        coordinates = feature.get("geometry", {}).get("coordinates", [])

        if len(coordinates) < 2:
            continue

        stations.append(
            {
                "name": properties.get("name"),
                "address": properties.get("formatted"),
                "longitude": coordinates[0],
                "latitude": coordinates[1],
                "categories": properties.get("categories", []),
                "place_id": properties.get("place_id"),
            }
        )

    return stations
