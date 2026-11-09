from fuel_optimizer.services.geocoding_service import (
    geocode_station,
    GeocodingError,
)


def main():
    test_stations = [
        {
            "name": "WOODSHED OF BIG CABIN",
            "city": "Big Cabin",
            "state": "Oklahoma",
            "address": "31209 US 69",
        },
        {
            "name": "KWIK TRIP #796",
            "city": "Tomah",
            "state": "Wisconsin",
            "address": "310 E McCoy Blvd",
        },
        {
            "name": "PILOT TRAVEL CENTER #1243",
            "city": "Gila Bend",
            "state": "Arizona",
            "address": "3006 S Butterfield Trl",
        },
    ]
    for station in test_stations:
        print(f"\nSearching: {station['name']}")

        try:
            results = geocode_station(**station)

            if not results:
                print("No matching stations found.")
                continue

            for index, result in enumerate(results, start=1):
                rank = result.get("rank", {})

                print(f"\nCandidate {index}")
                print("Name:", result.get("name"))
                print("Address:", result.get("formatted"))
                print("Latitude:", result.get("lat"))
                print("Longitude:", result.get("lon"))
                print("Type:", result.get("result_type"))
                print("Category:", result.get("category"))
                print("Confidence:", rank.get("confidence"))

        except GeocodingError as exc:
            print("Error:", exc)


if __name__ == "__main__":
    main()
