from fuel_optimizer.services.station_matching_service import match_station
from fuel_optimizer.services.station_data_service import load_station_data

csv_stations = load_station_data()


def main():

    geo_stations = [
        {
            "name": "Kwik Trip",
            "address": "I-94, Tomah, WI",
            "city": "Tomah",
            "state_code": "WI",
            "latitude": 44.019212458,
            "longitude": -90.501937653,
        },
        {
            "name": "Kwik Trip",
            "address": "Sam Walton Avenue, Tomah, WI",
            "city": "Tomah",
            "state_code": "WI",
            "latitude": 44.0184763,
            "longitude": -90.506726,
        },
        {
            "name": "Kwik Trip",
            "address": "1504 Superior Avenue, Tomah, WI",
            "city": "Tomah",
            "state_code": "WI",
            "latitude": 43.9725227,
            "longitude": -90.5041962,
        },
        {
            "name": "Kwik Trip",
            "address": "310 East McCoy Boulevard, Tomah, WI",
            "city": "Tomah",
            "state_code": "WI",
            "latitude": 44.018874385,
            "longitude": -90.502561943,
        },
    ]

    print("Testing improved matching accuracy")
    print("=" * 70)

    for geo_station in geo_stations:

        result = match_station(geo_station, csv_stations)

        print(f"\nGeoapify location: {geo_station['address']}")
        print("Status:", result["status"])
        print("Reason:", result["reason"])

        matched = result.get("station")

        if matched:
            print("Matched CSV ID:", matched["station_id"])
            print("Matched CSV name:", matched["name"])
            print("Fuel price:", matched["average_price"])
            print("Distance:", result["distance_meters"], "meters")
        else:
            print("Matched CSV station: None")


if __name__ == "__main__":
    main()
