import os
from pathlib import Path

import requests
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parents[2]
load_dotenv(BASE_DIR / ".env")

GEOAPIFY_API_KEY = os.getenv("GEOAPIFY_API_KEY")
GEOCODING_URL = "https://api.geoapify.com/v1/geocode/search"


class GeocodingError(Exception):
    """Raised when a geocoding request fails."""


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
