from fuel_optimizer.services.fuel_station_service import (
    find_fuel_stations,
    FuelStationError,
)


def main():
    # A sample route segment around Tomah, Wisconsin.
    # Coordinates are [longitude, latitude].
    route_coordinates = [
        [-90.5500, 43.9800],
        [-90.5200, 44.0000],
        [-90.5000, 44.0200],
        [-90.4700, 44.0400],
    ]

    print("Searching for fuel stations along route...")

    try:
        stations = find_fuel_stations(
            route_coordinates=route_coordinates,
            buffer_meters=5000,
        )

        print(f"\nFuel stations found: {len(stations)}")

        for index, station in enumerate(stations, start=1):
            print(f"\nCandidate {index}")
            print("Name:", station["name"])
            print("Address:", station["address"])
            print("Latitude:", station["latitude"])
            print("Longitude:", station["longitude"])
            print("Categories:", station["categories"])
            print("Place ID:", station["place_id"])

    except FuelStationError as exc:
        print("API error:", exc)


if __name__ == "__main__":
    main()
