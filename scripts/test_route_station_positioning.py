from fuel_optimizer.services.route_station_service import (
    locate_stations_along_route,
)

# Same test route used for the Geoapify Places API test.
route_coordinates = [
    [-90.5500, 43.9800],
    [-90.5200, 44.0000],
    [-90.5000, 44.0200],
    [-90.4700, 44.0400],
]


# Previously returned Geoapify results.
fuel_stations = [
    {
        "name": "Casey's General Store",
        "longitude": -90.5043865,
        "latitude": 43.9908212,
    },
    {
        "name": "Kwik Trip",
        "longitude": -90.5019376535901,
        "latitude": 44.0192124581067,
    },
    {
        "name": "Kwik Trip",
        "longitude": -90.506726,
        "latitude": 44.0184763,
    },
    {
        "name": "Unnamed Fuel Station",
        "longitude": -90.5074081,
        "latitude": 43.9720209,
    },
    {
        "name": "Whitetail Crossing",
        "longitude": -90.4359317,
        "latitude": 44.0297338,
    },
    {
        "name": "Kwik Trip",
        "longitude": -90.5041962,
        "latitude": 43.9725227,
    },
    {
        "name": "BP",
        "longitude": -90.5015125,
        "latitude": 44.0174357,
    },
    {
        "name": "Shell",
        "longitude": -90.4938931,
        "latitude": 44.0195569,
    },
    {
        "name": "Kwik Trip",
        "longitude": -90.50256194327956,
        "latitude": 44.01887438500311,
    },
]


def main():
    print("Positioning fuel stations along route...\n")

    positioned_stations = locate_stations_along_route(
        route_coordinates=route_coordinates,
        fuel_stations=fuel_stations,
        max_distance_from_route_meters=5000,
    )

    print(f"Stations within route corridor: {len(positioned_stations)}")
    print("-" * 90)

    for index, station in enumerate(positioned_stations, start=1):
        print(f"\n{index}. {station['name']}")
        print(
            "   Position along route: "
            f"{station['distance_along_route_miles']:.2f} miles"
        )
        print(
            "   Distance from route: "
            f"{station['distance_from_route_miles']:.2f} miles"
        )
        print("   Estimated detour: " f"{station['estimated_detour_miles']:.2f} miles")


if __name__ == "__main__":
    main()
