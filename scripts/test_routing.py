from fuel_optimizer.services.geocoding_service import geocode_location
from fuel_optimizer.services.routing_service import get_route


def main():
    start = geocode_location("New York, NY")
    destination = geocode_location("Philadelphia, PA")

    print("START:")
    print(start)

    print("\nDESTINATION:")
    print(destination)

    route = get_route(start, destination)

    print("\nROUTE:")
    print(f"Distance: {route['distance_meters'] / 1609.344:.2f} miles")
    print(f"Duration: {route['duration_seconds'] / 3600:.2f} hours")
    print(f"Coordinates: {len(route['coordinates'])}")

    print("\nFirst coordinate:", route["coordinates"][0])
    print("Last coordinate:", route["coordinates"][-1])


if __name__ == "__main__":
    main()
