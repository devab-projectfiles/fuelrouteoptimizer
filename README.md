# FuelRoute Optimizer

Plan a driving route, find fuel stops along the way, connect eligible stops to fuel prices, and estimate a cost-conscious refueling plan.

FuelRoute Optimizer is a Django REST API for drivers and fleet applications. It combines route, map, and station-price data into one route-planning workflow, while keeping discovered fuel locations visible even when they do not have a confirmed price match.

## What it does

Given a starting location and destination, the API:

1. Converts both locations into coordinates.
2. Calculates a driving route and its distance and duration.
3. Finds fuel-related points of interest near the route.
4. Positions each fuel POI along the route and estimates its detour.
5. Matches eligible POIs to the station-price dataset when verified location evidence is available.
6. Uses reliable price matches to estimate fuel purchases, refueling stops, and total purchase cost.

Unmatched and ambiguous POIs remain in the response with their map details and match status. Only reliable CSV price matches are passed to the optimizer.

## How the route plan is built

```text
Start + destination
        |
        v
  Geocode locations
        |
        v
  Driving route ----------------> distance and duration
        |
        v
  Fuel POIs near route
        |
        v
  Route position and detour estimate
        |
        +-- Reliable station-price match --> cost optimization
        +-- Ambiguous or unmatched POI ----> returned without a price
```

FuelRoute Optimizer uses Geoapify for geocoding, driving directions, and fuel-place discovery. Fuel POIs are searched within a default 5 km corridor around the route using the `service.vehicle.fuel` category. Route geometry is simplified before the Places request to reduce request size.

## Fuel and cost model

The current vehicle defaults are **10 miles per gallon** and a **50-gallon tank**. The optimizer estimates how much fuel is needed to reach future stations, chooses a cost-conscious sequence of reachable matched stations, and reports estimated gallons purchased and purchase cost. An estimated station detour is based on its distance from the route.

These defaults are defined in `fuel_optimizer/services/fuel_calculations.py` and can be changed in code. The route API currently accepts the start and destination; it does not accept vehicle settings in the request.

## API

### `POST /api/route/`

Request JSON:

```json
{
  "start": "Chicago, IL",
  "destination": "Madison, WI"
}
```

Both fields are required, and they must refer to different locations.

The response includes the resolved endpoints, route geometry and trip measurements, all positioned fuel POIs, CSV match details, and the fuel optimization result. A positioned station includes fields such as:

```json
{
  "name": "Kwik Trip",
  "address": "Example address",
  "latitude": 43.9,
  "longitude": -90.5,
  "distance_along_route_miles": 120.4,
  "distance_from_route_miles": 0.12,
  "estimated_detour_miles": 0.24,
  "csv_match_status": "probable_match",
  "csv_match_reason": "Station name, verified address, and geographic distance agree",
  "fuel_price": 3.28,
  "csv_station": {
    "station_id": "9",
    "name": "KWIK TRIP #796",
    "average_price": "3.287333"
  }
}
```

For a POI without a reliable price match, `csv_station` and `fuel_price` are `null`, and `csv_match_status` explains the match outcome. Match statuses are `probable_match`, `ambiguous`, and `unmatched`.

The `fuel_optimization` object reports total route distance, estimated distance including station detours, estimated fuel consumption, gallons and cost purchased, remaining fuel, and recommended stops.

## Station and price data

The project keeps source prices and location verification in separate files:

| File | Purpose |
| --- | --- |
| `data/fuel-prices-for-be-assessment.csv` | Original station-price source data |
| `data/fuel_stations_preprocessed.csv` | One normalized record per station, with average price and record count |
| `data/verified_station_coordinates.csv` | Verified coordinates and their source, joined by `station_id` |

The preprocessed station file has these fields:

```text
station_id,name,address,city,state,rack_id,average_price,price_record_count,latitude,longitude
```

The verified-coordinate file has these fields:

```text
station_id,latitude,longitude,verified_address,source
```

`station_id` is the join key. Add verified locations to the coordinate file with a traceable source; the API only attaches CSV prices when the station match satisfies the matching rules. Keeping the original price file separate makes it possible to refresh or enrich locations without changing source prices.

To rebuild the normalized station file from the original CSV:

```powershell
python -m scripts.preprocess_stations
```

## Setup

### Requirements

- Python 3.12
- A Geoapify API key

### Windows PowerShell

Create and activate a virtual environment, then install the project dependencies:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Create a `.env` file in the project root. Start from `.env.example` and set the Geoapify key:

```dotenv
DJANGO_SECRET_KEY=replace-with-a-local-secret
DJANGO_DEBUG=True
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1
GEOAPIFY_API_KEY=your-geoapify-api-key
```

Keep `.env` private; it is excluded from version control.

### Start the API

```powershell
python manage.py runserver
```

The development server runs at `http://127.0.0.1:8000`. Send route requests to `http://127.0.0.1:8000/api/route/` with `Content-Type: application/json`.

Example using PowerShell:

```powershell
$body = @{
    start = "Chicago, IL"
    destination = "Madison, WI"
} | ConvertTo-Json

Invoke-RestMethod `
    -Uri "http://127.0.0.1:8000/api/route/" `
    -Method Post `
    -ContentType "application/json" `
    -Body $body
```

## Configuration and integrations

The application reads the `GEOAPIFY_API_KEY` environment variable for geocoding, routing, and Places API requests. A route request calls these services to resolve both endpoints, calculate the route, and discover fuel POIs.

| Component | Responsibility |
| --- | --- |
| `geocoding_service.py` | Resolve user-entered locations |
| `routing_service.py` | Request driving routes and trip measurements |
| `fuel_station_service.py` | Find fuel POIs around a route |
| `route_station_service.py` | Calculate route position and detour estimates |
| `station_data_service.py` | Load normalized prices and verified coordinates |
| `station_matching_service.py` | Match map POIs to CSV station records |
| `optimization_service.py` | Select cost-conscious refueling stops |
| `fuel_optimizer/api/views.py` | Coordinate the API workflow and response |

## Run automated tests

```powershell
python manage.py test fuel_optimizer.tests
```

The `scripts/test_*.py` modules also provide focused examples for routing, station positioning, matching, and fuel optimization. Scripts that use live Geoapify services require a configured API key and make external API requests.

## License and data attribution

Project code and station-price data are separate concerns. Follow the terms that apply to the supplied price dataset and any third-party location data used with it. If OpenStreetMap data is included in a deployed or distributed dataset, provide the required OpenStreetMap attribution and observe the ODbL terms.
