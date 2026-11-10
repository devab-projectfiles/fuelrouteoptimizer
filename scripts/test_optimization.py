from fuel_optimizer.services.optimization_service import optimize_fuel_stops


def make_station(name, distance, price):
    return {
        "name": name,
        "distance_along_route_miles": distance,
        "estimated_detour_miles": 0,
        "fuel_price": price,
        "csv_station": {"station_id": name},
    }


def run_test(
    title,
    route_distance,
    stations,
    initial_fuel=50,
    expected_cost=None,
    expected_gallons=None,
    expected_stops=None,
):

    print("\n" + "=" * 65)
    print(title)
    print("=" * 65)

    result = optimize_fuel_stops(
        total_route_distance_miles=route_distance,
        matched_stations=stations,
        initial_fuel_gallons=initial_fuel,
    )

    print(f"Route distance: {route_distance} miles")
    print(f"Initial fuel: {initial_fuel} gallons")
    print(f"Fuel purchased: {result['total_gallons_purchased']:.2f} gallons")
    print(f"Total cost: ${result['total_purchase_cost']:.2f}")
    print(f"Remaining fuel: {result['remaining_fuel_gallons']:.2f} gallons")
    print(f"Number of stops: {len(result['stops'])}")

    for stop in result["stops"]:
        print(
            f"  {stop['station_name']}: "
            f"{stop['gallons_purchased']:.2f} gallons "
            f"at ${stop['fuel_price']:.2f}/gallon "
            f"= ${stop['purchase_cost']:.2f}"
        )

    if expected_cost is not None:
        assert abs(result["total_purchase_cost"] - expected_cost) < 0.01

    if expected_gallons is not None:
        assert abs(result["total_gallons_purchased"] - expected_gallons) < 0.01

    if expected_stops is not None:
        assert len(result["stops"]) == expected_stops

    print("TEST PASSED")


def main():

    # TEST 1: 100 miles, full tank
    run_test(
        "TEST 1: 100-MILE ROUTE",
        100,
        [],
        expected_cost=0,
        expected_gallons=0,
        expected_stops=0,
    )

    # TEST 2: 400 miles, full tank
    run_test(
        "TEST 2: 400-MILE ROUTE",
        400,
        [make_station("A", 200, 3.00)],
        expected_cost=0,
        expected_gallons=0,
        expected_stops=0,
    )

    # TEST 3: 499 miles, full tank
    run_test(
        "TEST 3: 499-MILE ROUTE",
        499,
        [make_station("A", 200, 3.00)],
        expected_cost=0,
        expected_gallons=0,
        expected_stops=0,
    )

    # TEST 4: Exactly 500 miles, full tank
    run_test(
        "TEST 4: EXACTLY 500 MILES",
        500,
        [
            make_station("A", 200, 3.00),
            make_station("B", 400, 4.00),
        ],
        expected_cost=0,
        expected_gallons=0,
        expected_stops=0,
    )

    # TEST 5: 501 miles, full tank
    run_test(
        "TEST 5: 501-MILE ROUTE",
        501,
        [make_station("A", 400, 3.00)],
        expected_cost=0.30,
        expected_gallons=0.10,
        expected_stops=1,
    )

    # TEST 6: Partial refueling, buy 10 gallons
    run_test(
        "TEST 6: BUY 10 GALLONS",
        600,
        [make_station("A", 400, 3.00)],
        expected_cost=30,
        expected_gallons=10,
        expected_stops=1,
    )

    # TEST 7: Partial refueling, buy 20 gallons
    run_test(
        "TEST 7: BUY 20 GALLONS",
        700,
        [make_station("A", 400, 3.00)],
        expected_cost=60,
        expected_gallons=20,
        expected_stops=1,
    )

    # TEST 8: Partial refueling, buy 30 gallons
    run_test(
        "TEST 8: BUY 30 GALLONS",
        800,
        [make_station("A", 400, 3.00)],
        expected_cost=90,
        expected_gallons=30,
        expected_stops=1,
    )

    # TEST 9: Basic optimization
    run_test(
        "TEST 9: BASIC FUEL OPTIMIZATION",
        900,
        [
            make_station("A", 200, 2.00),
            make_station("B", 400, 4.00),
            make_station("C", 600, 3.00),
        ],
        expected_cost=100,
        expected_gallons=40,
        expected_stops=2,
    )

    # TEST 10: Cheaper station ahead
    run_test(
        "TEST 10: CHEAPER STATION AHEAD",
        400,
        [
            make_station("A", 100, 5.00),
            make_station("B", 200, 2.00),
        ],
        initial_fuel=10,
        expected_cost=90,
        expected_gallons=30,
        expected_stops=2,
    )

    # TEST 11: Cheapest reachable station
    run_test(
        "TEST 11: CHEAPEST REACHABLE STATION",
        800,
        [
            make_station("A", 100, 5.00),
            make_station("B", 200, 2.00),
            make_station("C", 450, 3.00),
            make_station("D", 700, 4.00),
        ],
        expected_cost=70,
        expected_gallons=30,
        expected_stops=2,
    )


if __name__ == "__main__":
    main()
