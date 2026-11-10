from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from .serializers import RouteRequestSerializer

from fuel_optimizer.services.geocoding_service import (
    geocode_location,
    GeocodingError,
)

from fuel_optimizer.services.routing_service import (
    get_route,
    RoutingError,
)

from fuel_optimizer.services.fuel_station_service import (
    find_fuel_stations,
    FuelStationError,
)

from fuel_optimizer.services.route_station_service import (
    locate_stations_along_route,
)

from fuel_optimizer.services.station_data_service import (
    load_station_data,
)

from fuel_optimizer.services.station_matching_service import (
    match_station,
)

from fuel_optimizer.services.optimization_service import (
    optimize_fuel_stops,
    OptimizationError,
)

METERS_PER_MILE = 1609.344


class RouteOptimizationView(APIView):

    def post(self, request):

        # 1. Validate request data.
        serializer = RouteRequestSerializer(data=request.data)

        if not serializer.is_valid():
            return Response(
                {
                    "error": "Invalid request.",
                    "details": serializer.errors,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        start_location = serializer.validated_data["start"]
        destination_location = serializer.validated_data["destination"]

        # 7. Match discovered stations against CSV stations.
        matched_stations = []
        station_results = []

        try:

            # 2. Geocode start and destination.
            start = geocode_location(start_location)
            destination = geocode_location(destination_location)

            # 3. Calculate the driving route.
            route = get_route(start, destination)

            route_distance_miles = route["distance_meters"] / METERS_PER_MILE

            route_coordinates = route["coordinates"]

            # 4. Discover fuel stations along the route.
            discovered_stations = find_fuel_stations(route_coordinates)

            # 5. Calculate station positions relative to the route.
            positioned_stations = locate_stations_along_route(
                route_coordinates,
                discovered_stations,
            )

            # 6. Load fuel prices from the assessment CSV.
            csv_stations = load_station_data()
            match_status_counts = {
                "probable_match": 0,
                "ambiguous": 0,
                "unmatched": 0,
            }

            for geo_station in positioned_stations:
                match = match_station(geo_station, csv_stations)

                match_status = match["status"]

                station_result = {
                    **geo_station,
                    "csv_match_status": match_status,
                    "csv_match_reason": match["reason"],
                    "csv_station": None,
                    "fuel_price": None,
                }

                if match_status in match_status_counts:
                    match_status_counts[match_status] += 1

                if match_status == "probable_match":
                    csv_station = match["station"]
                    station_result["fuel_price"] = float(csv_station["average_price"])
                    station_result["csv_station"] = csv_station
                    matched_stations.append(station_result)

                station_results.append(station_result)
            print("\nSTATION MATCHING DIAGNOSTICS")
            print("----------------------------")
            print("Geoapify discovered:", len(discovered_stations))
            print("Positioned stations:", len(positioned_stations))
            print("CSV stations:", len(csv_stations))
            print("Matching results:", match_status_counts)
            print("Reliable matches:", len(matched_stations))
            # 8. Optimize fuel purchases.
            optimization = optimize_fuel_stops(
                total_route_distance_miles=route_distance_miles,
                matched_stations=matched_stations,
            )

            # 9. Return the complete result.
            return Response(
                {
                    "start": start,
                    "destination": destination,
                    "route": {
                        "distance_miles": round(
                            route_distance_miles,
                            2,
                        ),
                        "distance_kilometers": round(
                            route_distance_miles * 1.609344,
                            2,
                        ),
                        "duration_seconds": route["duration_seconds"],
                        "geometry": {
                            "type": "LineString",
                            "coordinates": route_coordinates,
                        },
                    },
                    "stations": {
                        "discovered": len(discovered_stations),
                        "positioned": len(positioned_stations),
                        "reliable_price_matches": len(matched_stations),
                        "items": station_results,
                    },
                    "fuel_optimization": optimization,
                },
                status=status.HTTP_200_OK,
            )

        except GeocodingError as exc:
            return Response(
                {"error": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        except RoutingError as exc:
            return Response(
                {"error": str(exc)},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        except FuelStationError as exc:
            return Response(
                {"error": str(exc)},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        except OptimizationError as exc:
            return Response(
                {
                    "error": "Fuel optimization failed.",
                    "details": str(exc),
                    "reliable_price_matches": len(matched_stations),
                    # "error": "Fuel station discovery service is temporarily unavailable."
                },
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
                # status=status.HTTP_502_BAD_GATEWAY,
            )

        except (ValueError, KeyError) as exc:
            return Response(
                {
                    "error": "Unable to process route data.",
                    "details": str(exc),
                },
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
