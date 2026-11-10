import csv
import json
import os
import time

from pathlib import Path

import requests
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parents[1]

load_dotenv(BASE_DIR / ".env", override=True)

INPUT_FILE = BASE_DIR / "data" / "fuel_stations_preprocessed.csv"

OUTPUT_FILE = BASE_DIR / "data" / "geocoded_station_candidates.csv"

PROGRESS_FILE = BASE_DIR / "data" / "geocoding_progress.json"

BATCH_URL = "https://api.geoapify.com/v1/batch/geocode/search"

BATCH_SIZE = 1000

POLL_INTERVAL_SECONDS = 60

MAX_WAIT_SECONDS = 30 * 60

load_dotenv(BASE_DIR / ".env")

GEOAPIFY_API_KEY = os.getenv("GEOAPIFY_API_KEY")


OUTPUT_FIELDS = [
    "station_id",
    "original_name",
    "original_address",
    "original_city",
    "original_state",
    "latitude",
    "longitude",
    "geocoded_address",
    "country_code",
    "result_type",
    "geocoding_confidence",
    "match_type",
    "coordinate_status",
    "source",
]


def load_progress():
    if not PROGRESS_FILE.exists():
        return {
            "next_index": 0,
            "job_id": None,
            "batch_start": None,
            "batch_size": 0,
        }

    with PROGRESS_FILE.open("r", encoding="utf-8") as file:
        return json.load(file)


def save_progress(progress):
    with PROGRESS_FILE.open("w", encoding="utf-8") as file:
        json.dump(progress, file, indent=4)


def load_stations():
    with INPUT_FILE.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as file:
        return list(csv.DictReader(file))


def build_address(station):
    return (
        f"{station['name']}, "
        f"{station['address']}, "
        f"{station['city']}, "
        f"{station['state']}, "
        "United States"
    )


def submit_batch(addresses):

    try:
        response = requests.post(
            BATCH_URL,
            params={
                "apiKey": GEOAPIFY_API_KEY,
                "lang": "en",
                "type": "amenity",
                "countrycodes": "us",
            },
            json=addresses,
            timeout=60,
        )

    except requests.RequestException:
        raise RuntimeError(
            "Could not submit geocoding batch. "
            "Check your internet connection and try again."
        ) from None

    if response.status_code != 202:
        raise RuntimeError(
            f"Batch submission failed: HTTP {response.status_code}. "
            f"{response.text[:500]}"
        )

    return response.json()["id"]


def get_batch_results(job_id):

    response = requests.get(
        BATCH_URL,
        params={
            "id": job_id,
            "apiKey": GEOAPIFY_API_KEY,
            "format": "json",
        },
        timeout=60,
    )

    if response.status_code == 202:
        return None

    if response.status_code != 200:
        raise RuntimeError(
            f"Batch retrieval failed: HTTP {response.status_code}. "
            f"{response.text[:500]}"
        )

    return response.json()


def classify_result(result):

    if not result:
        return "not_found"

    latitude = result.get("lat")
    longitude = result.get("lon")

    if latitude is None or longitude is None:
        return "not_found"

    if result.get("country_code") != "us":
        return "needs_review"

    rank = result.get("rank", {})

    confidence = rank.get("confidence", 0)

    match_type = rank.get("match_type", "")

    if confidence >= 0.8 and match_type == "full_match":
        return "candidate"

    return "needs_review"


def save_results(stations, results, start_index):

    existing = {}

    if OUTPUT_FILE.exists():
        with OUTPUT_FILE.open(
            "r",
            encoding="utf-8-sig",
            newline="",
        ) as file:
            for row in csv.DictReader(file):
                existing[row["station_id"]] = row

    for index, station in enumerate(stations):

        result = results[index] if index < len(results) else {}

        rank = result.get("rank", {})

        existing[station["station_id"]] = {
            "station_id": station["station_id"],
            "original_name": station["name"],
            "original_address": station["address"],
            "original_city": station["city"],
            "original_state": station["state"],
            "latitude": result.get("lat"),
            "longitude": result.get("lon"),
            "geocoded_address": result.get("formatted"),
            "country_code": result.get("country_code"),
            "result_type": result.get("result_type"),
            "geocoding_confidence": rank.get("confidence"),
            "match_type": rank.get("match_type"),
            "coordinate_status": classify_result(result),
            "source": "Geoapify",
        }

    with OUTPUT_FILE.open(
        "w",
        encoding="utf-8",
        newline="",
    ) as file:

        writer = csv.DictWriter(
            file,
            fieldnames=OUTPUT_FIELDS,
        )

        writer.writeheader()

        for row in existing.values():
            writer.writerow(row)


def main():

    if not GEOAPIFY_API_KEY:
        raise RuntimeError("GEOAPIFY_API_KEY is missing.")

    stations = load_stations()

    progress = load_progress()

    next_index = progress["next_index"]

    if next_index >= len(stations):
        print("All stations have already been processed.")
        return

    # Resume an existing job or submit the next batch.
    if progress["job_id"]:

        job_id = progress["job_id"]

        start_index = progress["batch_start"]

        batch_size = progress["batch_size"]

        print("Resuming existing batch:", job_id)

    else:

        start_index = next_index

        batch = stations[start_index : start_index + BATCH_SIZE]

        addresses = [build_address(station) for station in batch]

        print("Submitting batch...")
        print("Starting record:", start_index + 1)
        print("Batch size:", len(batch))

        job_id = submit_batch(addresses)

        batch_size = len(batch)

        progress["job_id"] = job_id
        progress["batch_start"] = start_index
        progress["batch_size"] = batch_size

        save_progress(progress)

        print("Batch submitted successfully.")
        print("Job ID:", job_id)

    # Poll the existing job.
    started_at = time.monotonic()

    while True:

        results = get_batch_results(job_id)

        if results is not None:
            break

        if time.monotonic() - started_at >= MAX_WAIT_SECONDS:
            print("Batch is still processing.")
            print("Progress has been saved.")
            print("Run this script again to resume.")
            return

        print("Batch still processing. Waiting 60 seconds...")
        time.sleep(POLL_INTERVAL_SECONDS)

    batch_stations = stations[start_index : start_index + batch_size]

    if len(results) != batch_size:
        raise RuntimeError(f"Expected {batch_size} results, received {len(results)}.")

    save_results(
        batch_stations,
        results,
        start_index,
    )

    # Mark this batch as completed.
    progress["next_index"] = start_index + batch_size
    progress["job_id"] = None
    progress["batch_start"] = None
    progress["batch_size"] = 0

    save_progress(progress)

    print("\nBATCH COMPLETED")
    print("----------------------------")
    print("Processed:", batch_size)
    print("Total processed:", progress["next_index"])
    print("Total stations:", len(stations))
    print("Remaining:", len(stations) - progress["next_index"])


if __name__ == "__main__":
    main()
