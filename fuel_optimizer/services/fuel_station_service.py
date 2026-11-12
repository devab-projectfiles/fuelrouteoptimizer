import os
import json
from pathlib import Path
from shapely.geometry import LineString

import requests
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parents[2]
load_dotenv(BASE_DIR / ".env")

GEOAPIFY_API_KEY = os.getenv("GEOAPIFY_API_KEY")

PLACES_URL = "https://api.geoapify.com/v2/places"


class FuelStationError(Exception):
    """this is raised when fuel station discovery fails."""


def simplify_route_coordinates(
    route_coordinates,
    tolerance_meters=100,
):
    """
    what this does is it just simplify route geometry to reduce the Geoapify request size that unfortunately consume my time debugging.
    """
    from pyproj import Transformer

    forward_transformer = Transformer.from_crs(
        "EPSG:4326",
        "EPSG:5070",
        always_xy=True,
    )

    reverse_transformer = Transformer.from_crs(
        "EPSG:5070",
        "EPSG:4326",
        always_xy=True,
    )

    route = LineString(route_coordinates)

    projected_route = LineString(
        [
            forward_transformer.transform(longitude, latitude)
            for longitude, latitude in route_coordinates
        ]
    )

    simplified_route = projected_route.simplify(
        tolerance_meters,
        preserve_topology=True,
    )

    simplified_coordinates = [
        reverse_transformer.transform(x, y) for x, y in simplified_route.coords
    ]

    return simplified_coordinates


def find_fuel_stations(route_coordinates, buffer_meters=5000):
    """
    this Finds fuel stations within a corridor around a route. using the api from geoapify. also at the end it returns a list of normalized fuel station dictionaries.
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

        if not -90 <= longitude <= 90:
            raise ValueError("Invalid latitude")

        if not 0 < buffer_meters < 10000:
            raise ValueError("Buffer must be between 0 and 10000 meters.")

    simplified_coordinates = simplify_route_coordinates(
        route_coordinates,
        tolerance_meters=100,
    )

    payload = {
        "categories": ["service.vehicle.fuel"],
        "filter": {
            "type": "polyline",
            "geometry": {
                "type": "LineString",
                "coordinates": simplified_coordinates,
            },
            "buffer": buffer_meters,
        },
        "limit": 100,
        "offset": 0,
    }

    geometry_json = json.dumps(
        payload["filter"]["geometry"],
        separators=(",", ":"),
    )

    print("Original coordinates:", len(route_coordinates))
    print("Simplified coordinates:", len(simplified_coordinates))
    print(
        "Simplified geometry size:",
        len(geometry_json.encode("utf-8")),
    )

    try:
        response = requests.post(
            PLACES_URL,
            params={"apiKey": GEOAPIFY_API_KEY},
            json=payload,
            timeout=30,
        )

        if not response.ok:
            raise FuelStationError(
                f"Geoapify Places API returned HTTP {response.status_code}: "
                f"{response.text[:1000]}"
            )

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
                "city": properties.get("city"),
                "state": properties.get("state"),
                "state_code": properties.get("state_code"),
                "longitude": coordinates[0],
                "latitude": coordinates[1],
                "categories": properties.get("categories", []),
                "place_id": properties.get("place_id"),
            }
        )

    return stations
