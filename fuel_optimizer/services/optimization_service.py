from fuel_optimizer.services.fuel_calculations import (
    MPG,
    TANK_CAPACITY_GALLONS,
    calculate_fuel_consumption,
    calculate_refuel_cost,
)


class OptimizationError(Exception):
    """Raised when fuel optimization cannot be completed."""


def calculate_travel_distance(current, destination):
    """
    Estimate driving distance between two route positions,
    including approximate station detours.
    """

    route_distance = (
        destination["distance_along_route_miles"]
        - current["distance_along_route_miles"]
    )

    current_offset = current.get("distance_from_route_miles", 0)
    destination_offset = destination.get("distance_from_route_miles", 0)

    return route_distance + current_offset + destination_offset


def optimize_fuel_stops(
    total_route_distance_miles,
    matched_stations,
    initial_fuel_gallons=TANK_CAPACITY_GALLONS,
    mpg=MPG,
    tank_capacity=TANK_CAPACITY_GALLONS,
):
    if total_route_distance_miles <= 0:
        raise ValueError("Route distance must be positive.")

    if mpg <= 0 or tank_capacity <= 0:
        raise ValueError("MPG and tank capacity must be positive.")

    if not 0 <= initial_fuel_gallons <= tank_capacity:
        raise ValueError("Invalid initial fuel quantity.")

    max_range = mpg * tank_capacity

    # Validate and sort stations.
    stations = []

    for station in matched_stations:
        try:
            price = float(station["fuel_price"])
            position = float(station["distance_along_route_miles"])
            offset = float(station.get("distance_from_route_miles", 0))

        except (KeyError, TypeError, ValueError):
            continue

        if price <= 0 or offset < 0:
            continue

        if not 0 <= position <= total_route_distance_miles:
            continue

        stations.append(
            {
                **station,
                "fuel_price": price,
                "distance_along_route_miles": position,
                "distance_from_route_miles": offset,
            }
        )

    stations.sort(key=lambda station: station["distance_along_route_miles"])

    destination = {
        "distance_along_route_miles": total_route_distance_miles,
        "distance_from_route_miles": 0,
    }

    current = {
        "name": "START",
        "distance_along_route_miles": 0,
        "distance_from_route_miles": 0,
        "fuel_price": None,
    }

    remaining_fuel = float(initial_fuel_gallons)

    total_purchased = 0.0
    total_cost = 0.0
    total_distance = 0.0

    stops = []

    next_index = 0

    while True:

        distance_to_destination = calculate_travel_distance(
            current,
            destination,
        )

        # Case 1: Existing fuel is enough to reach the destination.
        if distance_to_destination <= remaining_fuel * mpg + 1e-9:

            remaining_fuel -= calculate_fuel_consumption(
                distance_to_destination,
                mpg,
            )

            total_distance += distance_to_destination
            break

        # Find future stations and their distances.
        future_stations = []

        for index in range(next_index, len(stations)):

            station = stations[index]

            distance = calculate_travel_distance(
                current,
                station,
            )

            if distance <= 0:
                continue

            future_stations.append(
                {
                    "index": index,
                    "station": station,
                    "distance": distance,
                }
            )

        # Case 2: We are at the starting point.
        # We cannot purchase fuel here.
        if current["fuel_price"] is None:

            reachable = [
                item
                for item in future_stations
                if item["distance"] <= remaining_fuel * mpg + 1e-9
            ]

            if not reachable:
                raise OptimizationError("No fuel station is reachable from the start.")

            target = min(
                reachable,
                key=lambda item: item["station"]["fuel_price"],
            )

        else:

            # Case 3: Find the first cheaper station reachable
            # with a full tank.
            cheaper_station = next(
                (
                    item
                    for item in future_stations
                    if (
                        item["station"]["fuel_price"] < current["fuel_price"]
                        and item["distance"] <= max_range
                    )
                ),
                None,
            )

            if cheaper_station is not None:

                # Buy only enough fuel to reach the cheaper station.
                target = cheaper_station

                gallons_to_purchase = max(
                    0.0,
                    target["distance"] / mpg - remaining_fuel,
                )

            # Case 4: No cheaper station is reachable,
            # but the destination is reachable with a full tank.
            elif distance_to_destination <= max_range:

                gallons_to_purchase = max(
                    0.0,
                    distance_to_destination / mpg - remaining_fuel,
                )

                purchase_cost = calculate_refuel_cost(
                    gallons_to_purchase,
                    current["fuel_price"],
                )

                if gallons_to_purchase > 0:

                    stops.append(
                        {
                            "station_name": current.get("name"),
                            "station_id": (
                                current.get("csv_station", {}).get("station_id")
                            ),
                            "fuel_price": current["fuel_price"],
                            "arrival_fuel_gallons": remaining_fuel,
                            "gallons_purchased": gallons_to_purchase,
                            "purchase_cost": float(purchase_cost),
                            "departure_fuel_gallons": (
                                remaining_fuel + gallons_to_purchase
                            ),
                        }
                    )

                total_purchased += gallons_to_purchase
                total_cost += float(purchase_cost)

                remaining_fuel += gallons_to_purchase

                remaining_fuel -= calculate_fuel_consumption(
                    distance_to_destination,
                    mpg,
                )

                total_distance += distance_to_destination
                break

            else:

                # Case 5: No cheaper station or destination
                # is reachable within the current tank range.
                reachable = [
                    item for item in future_stations if item["distance"] <= max_range
                ]

                if not reachable:
                    raise OptimizationError(
                        "No reachable fuel station can extend the journey."
                    )
                # Fill the tank and travel to the cheapest
                # reachable station.
                target = min(
                    reachable,
                    key=lambda item: item["station"]["fuel_price"],
                )

                gallons_to_purchase = tank_capacity - remaining_fuel

            # Purchase fuel at the CURRENT station.
            purchase_cost = calculate_refuel_cost(
                gallons_to_purchase,
                current["fuel_price"],
            )

            if gallons_to_purchase > 0:

                stops.append(
                    {
                        "station_name": current.get("name"),
                        "station_id": (
                            current.get("csv_station", {}).get("station_id")
                        ),
                        "fuel_price": current["fuel_price"],
                        "arrival_fuel_gallons": remaining_fuel,
                        "gallons_purchased": gallons_to_purchase,
                        "purchase_cost": float(purchase_cost),
                        "departure_fuel_gallons": (
                            remaining_fuel + gallons_to_purchase
                        ),
                    }
                )

            remaining_fuel += gallons_to_purchase

            total_purchased += gallons_to_purchase
            total_cost += float(purchase_cost)

        # Travel to the selected station.
        distance_to_target = target["distance"]

        fuel_consumed = calculate_fuel_consumption(
            distance_to_target,
            mpg,
        )

        if fuel_consumed > remaining_fuel + 1e-9:
            raise OptimizationError("Insufficient fuel to reach the selected station.")

        remaining_fuel -= fuel_consumed
        total_distance += distance_to_target

        current = target["station"]
        next_index = target["index"] + 1

    return {
        "total_route_distance_miles": total_route_distance_miles,
        "estimated_distance_with_detours_miles": total_distance,
        "total_fuel_consumed_gallons": calculate_fuel_consumption(
            total_distance,
            mpg,
        ),
        "total_gallons_purchased": total_purchased,
        "total_purchase_cost": round(total_cost, 2),
        "remaining_fuel_gallons": max(0.0, remaining_fuel),
        "stops": stops,
    }
