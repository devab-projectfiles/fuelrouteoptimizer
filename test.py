


# Accept distance in miles.
# Accept fuel efficiency in MPG.
# Return gallons consumed.
# Reject negative distances.
# Reject zero or negative MPG.

def calculate_fuel_consumption(distance, mpg):
    if distance < 0:
        return
    if mpg <= 0:
        raise ValueError("MPG must be greate than zero")
    return distance / mpg

print(calculate_fuel_consumption(150, 10))  # 15
print(calculate_fuel_consumption(-400, 10))  # ValueError: distance cannot be negative
print(calculate_fuel_consumption(500, 10))  # 50


# Requirements:

# Reject negative initial fuel.
# Reject negative distance.
# Reject zero or negative MPG.
# Calculate fuel consumed.
# Return remaining fuel.
# Raise an exception if the vehicle runs out of fuel.

def calculate_remaining_fuel(initial_fuel, distance, mpg):
    if initial_fuel <= 0:
        raise ValueError("Intial fuel must be greater than zero")
    if distance < 0:
        raise ValueError("distance cannot be negative")
    if mpg <= 0:
        raise ValueError("mpg must be greater thatn zero")
    remainfuel = initial_fuel - (distance / mpg)
    if remainfuel < 0:
        raise ValueError("Vehicle has run out of fuel and cannot complete the trip")
    return remainfuel

print(calculate_remaining_fuel(10, 150, 10))  # -5
print(calculate_remaining_fuel(10, 150, 0))  # ValueError: mpg must be greater than zero
print(calculate_remaining_fuel(10, -150, 10))  # ValueError: distance cannot be negative