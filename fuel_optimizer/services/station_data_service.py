import csv
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]

PREPROCESSED_FILE = BASE_DIR / "data" / "fuel_stations_preprocessed.csv"

VERIFIED_COORDINATES_FILE = BASE_DIR / "data" / "verified_station_coordinates.csv"


def load_station_data():
    stations = {}

    with PREPROCESSED_FILE.open(
        mode="r",
        encoding="utf-8-sig",
        newline="",
    ) as file:
        reader = csv.DictReader(file)

        for row in reader:
            station_id = row["station_id"]

            row["latitude"] = None
            row["longitude"] = None
            row["verified_address"] = None
            row["coordinate_source"] = None

            stations[station_id] = row

    with VERIFIED_COORDINATES_FILE.open(
        mode="r",
        encoding="utf-8-sig",
        newline="",
    ) as file:
        reader = csv.DictReader(file)

        for row in reader:
            station_id = row["station_id"]

            if station_id not in stations:
                continue

            stations[station_id]["latitude"] = float(row["latitude"])
            stations[station_id]["longitude"] = float(row["longitude"])
            stations[station_id]["verified_address"] = row["verified_address"]
            stations[station_id]["coordinate_source"] = row["source"]
            stations[station_id]["poi_name_aliases"] = [
                alias.strip()
                for alias in row.get("poi_name_aliases", "").split("|")
                if alias.strip()
            ]

    return list(stations.values())
