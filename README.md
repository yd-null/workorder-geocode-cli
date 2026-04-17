# workorder-geocode-cli

`workorder-geocode-cli` is a simple command-line tool that reads a Microsoft Dynamics CRM Work Order export (`.xlsx` or `.csv`) and fills missing latitude/longitude values using the Google Maps Geocoding API.

It is designed for non-technical use:

- You only provide the `.xlsx` or `.csv` file path as an argument.
- The API key is requested interactively.
- API key input is hidden while typing.

## What you need

- Python 3.10+
- A Google Maps API key with Geocoding API enabled

Install dependencies:

```bash
pip install -r requirements.txt
```

## Run the CLI

Show usage/help:

```bash
python3 workorder_geocode_cli.py -h
```

```bash
python3 workorder_geocode_cli.py "path/to/WorkOrders.xlsx"
```

To skip bounds checking for rows that already have latitude/longitude:

```bash
python3 workorder_geocode_cli.py --disable-bounds-check "path/to/WorkOrders.xlsx"
```

CSV input is also supported:

```bash
python3 workorder_geocode_cli.py "path/to/WorkOrders.csv"
```

If installed as a package (`pip install .`), you can run the command directly:

```bash
workorder-geocode-cli "path/to/WorkOrders.xlsx"
```

The script will then prompt:

```text
Google Maps API key (input hidden):
```

## Required spreadsheet headers

Your input file must include these headers exactly:

- `Address 1`
- `Address 2`
- `Address 3`
- `City`
- `State Or Province`
- `Postal Code`
- `Latitude`
- `Longitude`

Header notes:

- Headers must be on row 1.
- The first column is treated as the index/record ID column.

If any required header is missing, the script stops and tells you which ones are missing.

## Dynamics export shape

This tool expects the report layout exported from Microsoft Dynamics CRM Work Orders.

Use the filter setup shown in:

- `Work Order Filters.png`

That screenshot demonstrates the filter pattern used to generate the expected report shape (for example: status, parent work order, project status, and closed date range filters).

## Output

The tool writes a CSV into the same folder as the input file:

- `lat-lon-gmaps-api.csv`
- `lat-lon-gmaps-api(1).csv`
- `lat-lon-gmaps-api(2).csv`
- etc.

## Bounds configuration

Bounds are loaded from `bounds.json` in the project root:

```json
{
  "north": -8.0,
  "south": -45.0,
  "east": 156.0,
  "west": 104.0
}
```

If a row already has coordinates, these bounds are used to decide whether to skip or re-evaluate (unless you use `--disable-bounds-check`).

## Behavior summary

- If a row already has latitude and longitude within configured bounds, it is skipped.
- If existing coordinates are out of bounds, the row is geocoded again.
- If you run with `--disable-bounds-check`, any row with existing latitude and longitude is skipped without checking bounds.
- If address fields are empty but in-bounds coordinates already exist, the row is skipped.
- If address fields are empty and coordinates are out of bounds, the row is logged as `LAT/LON EXISTS OUTSIDE BOUNDS - NO FALLBACK ADDRESS` and skipped.
- If geocoding fails for a row, it is listed in the error section at the end.

## Security note

- Do not commit API keys to git.
- Do not add API keys to command arguments.
- This CLI prompts for the key at runtime with hidden input to reduce accidental exposure.

## Smoke tests

Run the basic smoke test suite:

```bash
python3 -m unittest tests/test_smoke.py -v
```

Run static fixture checks against `synthetic_work_orders_sample.xlsx`:

```bash
python3 -m unittest tests/test_static_fixture.py -v
```
