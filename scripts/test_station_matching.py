import csv

from fuel_optimizer.services.station_matching_service import match_station

CSV_FILE = "data/fuel_stations_preprocessed.csv"


def load_csv_stations():
    with open(CSV_FILE, encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def main():
    csv_stations = load_csv_stations()

    # here im trying to simulate Kwik Trip result.

    geo_station = {
        "name": "Kwik Trip",
        "address": (
            "Kwik Trip, 310 East McCoy Boulevard, "
            "Tomah, WI 54660, United States of America"
        ),
        "city": "Tomah",
        "state": "Wisconsin",
        "state_code": "WI",
        "latitude": 44.018874385,
        "longitude": -90.502561943,
    }

    result = match_station(geo_station, csv_stations)

    print("\nMatching result")
    print("------------------------")
    print("Status:", result["status"])
    print("Reason:", result["reason"])
    print("Score:", result["score"])

    matched = result["matched_station"]

    if matched:
        print("\nMatched CSV station")
        print("Station ID:", matched["station_id"])
        print("Name:", matched["name"])
        print("Address:", matched["address"])
        print("City:", matched["city"])
        print("State:", matched["state"])
        print("Average price:", matched["average_price"])


if __name__ == "__main__":
    main()
