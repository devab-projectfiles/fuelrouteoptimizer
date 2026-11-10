from fuel_optimizer.services.geocoding_service import geocode_location
from fuel_optimizer.services.routing_service import get_route
from fuel_optimizer.services.fuel_station_service import find_fuel_stations
from fuel_optimizer.services.route_station_service import (
    locate_stations_along_route,
)
from fuel_optimizer.services.station_data_service import load_station_data
from fuel_optimizer.services.station_matching_service import match_station


def main():

    print("=" * 65)
    print("FUEL ROUTE PIPELINE INTEGRATION TEST")
    print("=" * 65)

    # 1. Geocode locations
    print("\n1. Geocoding locations...")

    start = geocode_location("310 East McCoy Boulevard, Tomah, WI")

    destination = geocode_location("Madison, WI")

    print("Start:", start["formatted"])
    print("Destination:", destination["formatted"])

    # 2. Calculate route
    print("\n2. Calculating driving route...")

    route = get_route(start, destination)

    distance_miles = route["distance_meters"] / 1609.344

    print(f"Route distance: {distance_miles:.2f} miles")
    print(f"Route coordinates: {len(route['coordinates'])}")

    # 3. Discover fuel stations
    print("\n3. Discovering fuel stations...")

    discovered_stations = find_fuel_stations(route["coordinates"])

    print(f"Discovered stations: {len(discovered_stations)}")

    # 4. Position stations along route
    print("\n4. Positioning fuel stations...")

    positioned_stations = locate_stations_along_route(
        route["coordinates"],
        discovered_stations,
    )

    print(f"Stations within route corridor: {len(positioned_stations)}")

    # 5. Load CSV station data
    print("\n5. Loading CSV fuel prices...")

    csv_stations = load_station_data()

    print(f"CSV stations loaded: {len(csv_stations)}")

    # 6. Match discovered stations against CSV
    print("\n6. Matching discovered stations against CSV...")

    matched_stations = []

    for geo_station in positioned_stations:

        result = match_station(
            geo_station,
            csv_stations,
        )

        if result["status"] == "probable_match":

            csv_station = result["station"]

            matched_stations.append(
                {
                    **geo_station,
                    "csv_station": csv_station,
                    "fuel_price": float(csv_station["average_price"]),
                    "match_distance_meters": result["distance_meters"],
                }
            )

    # 7. Display results
    print("\n" + "=" * 65)
    print("PIPELINE RESULTS")
    print("=" * 65)

    print(f"Discovered stations: {len(discovered_stations)}")
    print(f"Positioned stations: {len(positioned_stations)}")
    print(f"Reliable price matches: {len(matched_stations)}")

    print("\nMATCHED STATIONS:")

    for station in matched_stations:

        print("\nName:", station["name"])
        print("CSV ID:", station["csv_station"]["station_id"])
        print("Fuel price:", station["fuel_price"])
        print(
            "Distance along route:",
            round(station["distance_along_route_miles"], 2),
            "miles",
        )
        print(
            "Estimated detour:",
            round(station["estimated_detour_miles"], 2),
            "miles",
        )

    print("\n" + "=" * 65)
    print("INTEGRATION TEST COMPLETED")
    print("=" * 65)


if __name__ == "__main__":
    main()
