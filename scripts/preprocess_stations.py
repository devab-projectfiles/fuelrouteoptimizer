import csv
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

INPUT_FILE = BASE_DIR / "data" / "fuel-prices-for-be-assessment.csv"
OUTPUT_FILE = BASE_DIR / "data" / "fuel_stations_preprocessed.csv"


def load_stations(file_path):
    """
    Load the original fuel-price CSV and group records by OPIS Truckstop ID.
    """

    stations = defaultdict(list)

    with open(file_path, encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)

        required_columns = {
            "OPIS Truckstop ID",
            "Truckstop Name",
            "Address",
            "City",
            "State",
            "Rack ID",
            "Retail Price",
        }

        missing_columns = required_columns - set(reader.fieldnames or [])

        if missing_columns:
            raise ValueError(f"Missing required CSV columns: {missing_columns}")

        for row_number, row in enumerate(reader, start=2):
            try:
                price = Decimal(row["Retail Price"])
            except (InvalidOperation, TypeError):
                raise ValueError(f"Invalid fuel price at CSV row {row_number}")

            if price <= 0:
                raise ValueError(f"Fuel price must be positive at CSV row {row_number}")

            station_id = row["OPIS Truckstop ID"].strip()

            if not station_id:
                raise ValueError(f"Missing station ID at CSV row {row_number}")

            row["Retail Price"] = price
            stations[station_id].append(row)

    return stations


def normalize_station(station_id, records):
    """
    this convert to us multiple price  into one normalized station record since having the same station id.
    """

    # im verifing same location and fuel rack for one id
    location_fields = [
        (record["Address"], record["City"], record["State"], record["Rack ID"])
        for record in records
    ]

    if len(set(location_fields)) != 1:
        raise ValueError(
            f"Station ID {station_id} has inconsistent location or rack data."
        )

    # looks for the most common station name.

    names = Counter(record["Truckstop Name"].strip() for record in records)

    canonical_name = names.most_common(1)[0][0]

    prices = [record["Retail Price"] for record in records]

    average_price = sum(prices) / Decimal(len(prices))

    first_record = records[0]

    return {
        "station_id": station_id,
        "name": canonical_name,
        "address": first_record["Address"].strip(),
        "city": first_record["City"].strip(),
        "state": first_record["State"].strip(),
        "rack_id": first_record["Rack ID"].strip(),
        "average_price": format(average_price, ".6f"),
        "price_record_count": len(prices),
        "latitude": "",
        "longitude": "",
    }


def save_stations(stations, output_file):
    """
    here im creating a new csv file with normalized station records
    """

    fieldnames = [
        "station_id",
        "name",
        "address",
        "city",
        "state",
        "rack_id",
        "average_price",
        "price_record_count",
        "latitude",
        "longitude",
    ]

    output_file.parent.mkdir(parents=True, exist_ok=True)

    with open(output_file, "w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)

        writer.writeheader()
        writer.writerows(stations)


def main():
    print("Loading original fuel-price dataset...")

    grouped_stations = load_stations(INPUT_FILE)

    print(f"Original records: {sum(len(v) for v in grouped_stations.values())}")
    print(f"Unique stations: {len(grouped_stations)}")

    print("Normalizing station records executes here...")

    normalized_stations = [
        normalize_station(station_id, records)
        for station_id, records in grouped_stations.items()
    ]

    normalized_stations.sort(key=lambda station: station["station_id"])

    save_stations(normalized_stations, OUTPUT_FILE)

    print("\nPreprocessing completed successfully.")
    print(f"Processed stations: {len(normalized_stations)}")
    print(f"Output file: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
