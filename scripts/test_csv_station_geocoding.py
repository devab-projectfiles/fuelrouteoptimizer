import csv
import os
from pathlib import Path

import requests
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

CSV_FILE = BASE_DIR / "data" / "fuel_stations_preprocessed.csv"

load_dotenv(BASE_DIR / ".env")

API_KEY = os.getenv("GEOAPIFY_API_KEY")

GEOCODING_URL = "https://api.geoapify.com/v1/geocode/search"


def geocode_address(address):
    response = requests.get(
        GEOCODING_URL,
        params={
            "text": address,
            "apiKey": API_KEY,
            "format": "json",
            "limit": 5,
        },
        timeout=30,
    )

    response.raise_for_status()

    return response.json().get("results", [])


def main():
    if not API_KEY:
        raise ValueError("GEOAPIFY_API_KEY is missing.")

    searches = [
        "I-94 Exit 143, US-12, State Highway 21, Tomah, WI, USA",
        "I-90 I-94 Exit 48, Oakdale, WI, USA",
        "I-90 I-94 Exit 48, Tomah, WI, USA",
    ]

    for address in searches:
        print("\n" + "=" * 70)
        print("Search:", address)

        results = geocode_address(address)

        if not results:
            print("No results.")
            continue

        for index, result in enumerate(results, start=1):
            rank = result.get("rank", {})

            print(f"\nCandidate {index}")
            print("Name:", result.get("name"))
            print("Address:", result.get("formatted"))
            print("Latitude:", result.get("lat"))
            print("Longitude:", result.get("lon"))
            print("Type:", result.get("result_type"))
            print("Confidence:", rank.get("confidence"))
            print("Match type:", rank.get("match_type"))


if __name__ == "__main__":
    main()
