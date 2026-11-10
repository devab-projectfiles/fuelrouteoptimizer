from pyproj import Transformer
from shapely.geometry import LineString, Point

# EPSG:5070 is a suitable projected coordinate system for the
# contiguous United States. It lets us calculate distances in meters.
PROJECTOR = Transformer.from_crs(
    "EPSG:4326",
    "EPSG:5070",
    always_xy=True,
)

METERS_PER_MILE = 1609.344


class RouteStationError(Exception):
    """Raised when route station positioning fails."""


def project_coordinates(longitude, latitude):
    """Convert longitude/latitude into projected meter coordinates."""
    return PROJECTOR.transform(longitude, latitude)


def locate_stations_along_route(
    route_coordinates,
    fuel_stations,
    max_distance_from_route_meters=5000,
):
    """
    Position fuel stations relative to a route.

    Returns stations with:
    - distance_along_route_miles
    - distance_from_route_miles
    - estimated_detour_miles

    Detour is estimated as twice the perpendicular distance
    from the station to the route.
    """

    if len(route_coordinates) < 2:
        raise RouteStationError("Route must contain at least two coordinates.")

    if max_distance_from_route_meters <= 0:
        raise ValueError("Maximum distance from route must be positive.")

    projected_route = []

    for coordinate in route_coordinates:
        if len(coordinate) != 2:
            raise RouteStationError(
                "Each route coordinate must contain longitude and latitude."
            )

        longitude, latitude = coordinate

        if not -180 <= longitude <= 180:
            raise RouteStationError("Invalid route longitude.")

        if not -90 <= latitude <= 90:
            raise RouteStationError("Invalid route latitude.")

        projected_route.append(project_coordinates(longitude, latitude))

    route_line = LineString(projected_route)

    if route_line.is_empty or route_line.length == 0:
        raise RouteStationError("Route geometry is invalid.")

    positioned_stations = []
    seen_place_ids = set()

    for station in fuel_stations:
        longitude = station.get("longitude")
        latitude = station.get("latitude")

        if longitude is None or latitude is None:
            continue

        try:
            longitude = float(longitude)
            latitude = float(latitude)
        except (TypeError, ValueError):
            continue

        if not -180 <= longitude <= 180:
            continue

        if not -90 <= latitude <= 90:
            continue

        place_id = station.get("place_id")

        # Remove exact duplicate Places API results.
        if place_id and place_id in seen_place_ids:
            continue

        if place_id:
            seen_place_ids.add(place_id)

        station_x, station_y = project_coordinates(
            longitude,
            latitude,
        )

        station_point = Point(station_x, station_y)

        distance_from_route = route_line.distance(station_point)

        # Ignore stations outside the route corridor.
        if distance_from_route > max_distance_from_route_meters:
            continue

        # Distance from the route's starting point to the nearest
        # point on the route.
        distance_along_route = route_line.project(station_point)

        # Approximation: drive from route to station, then back.
        estimated_detour = distance_from_route * 2

        positioned_stations.append(
            {
                **station,
                "distance_along_route_miles": (distance_along_route / METERS_PER_MILE),
                "distance_from_route_miles": (distance_from_route / METERS_PER_MILE),
                "estimated_detour_miles": (estimated_detour / METERS_PER_MILE),
            }
        )

    positioned_stations.sort(key=lambda station: station["distance_along_route_miles"])

    return positioned_stations
