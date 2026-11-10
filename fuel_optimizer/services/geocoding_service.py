import os
from pathlib import Path

import requests
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parents[2]
load_dotenv(BASE_DIR / ".env")

GEOAPIFY_API_KEY = os.getenv("GEOAPIFY_API_KEY")
GEOCODING_URL = "https://api.geoapify.com/v1/geocode/search"


class GeocodingError(Exception):
    """this is raised when a geocoding request fails."""


def geocode_station(name, city, state, address):
    if not GEOAPIFY_API_KEY:
        raise GeocodingError("GEOAPIFY_API_KEY is missing.")

    params = {
        "text": f"{name}, {address}, {city}, {state}, USA",
        "format": "json",
        "apiKey": GEOAPIFY_API_KEY,
        "limit": 5,
        "filter": "countrycode:us",
    }

    try:
        response = requests.get(
            GEOCODING_URL,
            params=params,
            timeout=20,
        )
        response.raise_for_status()
        data = response.json()

    except requests.RequestException as exc:
        raise GeocodingError(f"Geocoding request failed: {exc}") from exc

    return data.get("results", [])


def geocode_location(location):
    """
    this conversts user provided locations into latitude, longitude, and formatted address.
    """

    if not GEOAPIFY_API_KEY:
        raise GeocodingError("GEOAPIFY_API_KEY is missing.")

    if not location or not location.strip():
        raise ValueError("Location cannot be empty.")

    params = {
        "text": location,
        "format": "json",
        "apiKey": GEOAPIFY_API_KEY,
        "limit": 5,
        "filter": "countrycode:us",
    }

    try:
        response = requests.get(
            GEOCODING_URL,
            params=params,
            timeout=20,
        )

        response.raise_for_status()
        data = response.json()

    except requests.RequestException as exc:
        raise GeocodingError(f"Geocoding request failed: {exc}") from exc

    results = data.get("results", [])

    if not results:
        raise GeocodingError(f"Could not find a location matching: {location}")

    result = results[0]

    return {
        "latitude": result["lat"],
        "longitude": result["lon"],
        "formatted": result.get("formatted"),
        "confidence": result.get("rank", {}).get("confidence"),
    }
