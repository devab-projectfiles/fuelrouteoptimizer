import os
from pathlib import Path

import requests
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parents[2]
load_dotenv(BASE_DIR / ".env")

GEOAPIFY_API_KEY = os.getenv("GEOAPIFY_API_KEY")

ROUTING_URL = "https://api.geoapify.com/v1/routing"


class RoutingError(Exception):
    """Raised when route calculation fails."""


def get_route(start, destination):
    """
    Calculate a driving route between two geographic locations.

    start and destination must contain:
        latitude
        longitude

    Returns:
        coordinates: route coordinates as [longitude, latitude]
        distance_meters: total route distance
        duration_seconds: estimated travel time
    """

    if not GEOAPIFY_API_KEY:
        raise RoutingError("GEOAPIFY_API_KEY is missing.")

    for location in (start, destination):
        latitude = location.get("latitude")
        longitude = location.get("longitude")

        if latitude is None or longitude is None:
            raise ValueError("Both latitude and longitude are required.")

        if not -90 <= float(latitude) <= 90:
            raise ValueError("Invalid latitude.")

        if not -180 <= float(longitude) <= 180:
            raise ValueError("Invalid longitude.")

    waypoints = (
        f"{start['latitude']},{start['longitude']}|"
        f"{destination['latitude']},{destination['longitude']}"
    )

    params = {
        "waypoints": waypoints,
        "mode": "drive",
        "format": "geojson",
        "apiKey": GEOAPIFY_API_KEY,
    }

    try:
        response = requests.get(
            ROUTING_URL,
            params=params,
            timeout=30,
        )

        response.raise_for_status()
        data = response.json()

    except requests.RequestException as exc:
        raise RoutingError(f"Route calculation failed: {exc}") from exc

    features = data.get("features", [])

    if not features:
        raise RoutingError("No driving route was returned.")

    feature = features[0]

    geometry = feature.get("geometry", {})
    properties = feature.get("properties", {})

    geometry_type = geometry.get("type")
    raw_coordinates = geometry.get("coordinates", [])

    if geometry_type == "LineString":
        coordinates = raw_coordinates

    elif geometry_type == "MultiLineString":
        coordinates = [coordinate for line in raw_coordinates for coordinate in line]

    else:
        raise RoutingError(f"Unsupported route geometry: {geometry_type}")

    if len(coordinates) < 2:
        raise RoutingError("The returned route has invalid geometry.")

    distance_meters = properties.get("distance")
    duration_seconds = properties.get("time")

    if distance_meters is None or duration_seconds is None:
        raise RoutingError("Route response is missing distance or duration.")

    return {
        "coordinates": coordinates,
        "distance_meters": distance_meters,
        "duration_seconds": duration_seconds,
    }
