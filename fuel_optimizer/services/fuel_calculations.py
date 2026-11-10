from decimal import Decimal

MPG = 10
TANK_CAPACITY_GALLONS = 50
MAX_RANGE_MILES = MPG * TANK_CAPACITY_GALLONS


def calculate_fuel_consumption(distance_miles, mpg=MPG):
    if distance_miles < 0:
        raise ValueError("Distance cannot be negative.")

    if mpg <= 0:
        raise ValueError("MPG must be greater than zero.")

    return distance_miles / mpg


def calculate_remaining_fuel(initial_fuel, distance_miles, mpg=MPG):

    if initial_fuel < 0:
        raise ValueError("Initial fuel cannot be negative.")

    consumed = calculate_fuel_consumption(
        distance_miles,
        mpg,
    )

    remaining = initial_fuel - consumed

    if remaining < -1e-9:
        raise ValueError("Insufficient fuel for this distance.")

    return max(0.0, remaining)


def calculate_refuel_cost(gallons, price_per_gallon):

    gallons = Decimal(str(gallons))
    price_per_gallon = Decimal(str(price_per_gallon))

    if gallons < 0:
        raise ValueError("Gallons cannot be negative.")

    if price_per_gallon < 0:
        raise ValueError("Fuel price cannot be negative.")

    return gallons * price_per_gallon
