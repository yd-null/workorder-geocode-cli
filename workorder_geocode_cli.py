#!/usr/bin/env python3

import json
import os
import sys
import warnings
from getpass import getpass
from pathlib import Path

REQUIRED_HEADERS = [
    "Address 1",
    "Address 2",
    "Address 3",
    "City",
    "State Or Province",
    "Postal Code",
    "Latitude",
    "Longitude",
]

ALLOWED_INPUT_EXTENSIONS = {".xlsx", ".csv"}

BOUNDS_CONFIG_FILE = "bounds.json"


class Colors:
    BLUE = ""
    GREEN = ""
    RED = ""
    YELLOW = ""
    RESET = ""
    BOLD = ""
    UNDERLINE = ""

    if os.name == "posix":
        BLUE = "\033[34m"
        GREEN = "\033[92m"
        RED = "\033[91m"
        YELLOW = "\033[33m"
        RESET = "\033[0m"
        BOLD = "\033[1m"
        UNDERLINE = "\033[4m"


def get_pandas_module():
    try:
        import pandas
    except ModuleNotFoundError as error:
        missing = error.name or "a required package"
        raise RuntimeError(
            f"Missing dependency: {missing}. "
            "Run 'pip install -r requirements.txt' and try again."
        ) from error

    return pandas


def print_usage() -> None:
    print(
        "Usage: workorder-geocode-cli [--disable-bounds-check] "
        "<INPUT_FILE.xlsx|INPUT_FILE.csv>"
    )
    print("")
    print("Flags:")
    print("  -h, --help              Show this help message and exit.")
    print(
        "  --disable-bounds-check  Skip bounds checks for rows with existing "
        "Latitude/Longitude."
    )


def parse_cli_args(argv: list[str]) -> tuple[str | None, bool, bool]:
    disable_bounds_check = False
    show_help = False
    input_args = []

    for arg in argv[1:]:
        if arg in {"-h", "--help"}:
            show_help = True
            continue
        if arg == "--disable-bounds-check":
            disable_bounds_check = True
            continue
        if arg.startswith("-"):
            raise ValueError(f"Unknown option: {arg}")
        input_args.append(arg)

    if show_help:
        return None, disable_bounds_check, True

    if len(input_args) != 1:
        raise ValueError("Require exactly one INPUT_FILE argument.")

    return input_args[0], disable_bounds_check, False


def validate_input_path(path_arg: str) -> Path:
    input_path = Path(path_arg).expanduser()

    if not input_path.exists() or not input_path.is_file():
        raise ValueError("INPUT_FILE is not a valid file path.")
    if input_path.suffix.lower() not in ALLOWED_INPUT_EXTENSIONS:
        raise ValueError("INPUT_FILE must be a .xlsx or .csv file.")

    return input_path.resolve()


def read_input_file(input_path: Path):
    pd = get_pandas_module()

    with warnings.catch_warnings(record=True):
        warnings.simplefilter("always")

        suffix = input_path.suffix.lower()
        if suffix == ".csv":
            return pd.read_csv(input_path, index_col=0, dtype=str)

        return pd.read_excel(input_path, index_col=0, dtype=str)


def load_bounds_config(config_path: Path) -> dict[str, float]:
    try:
        raw_config = json.loads(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise ValueError(f"Bounds config file not found: {config_path.name}") from error
    except json.JSONDecodeError as error:
        raise ValueError(f"Bounds config file is invalid JSON: {error}") from error

    if not isinstance(raw_config, dict):
        raise ValueError("Bounds config file must contain a JSON object.")

    required_keys = ["north", "south", "east", "west"]
    missing_keys = [key for key in required_keys if key not in raw_config]
    if missing_keys:
        raise ValueError(
            "Bounds config file is missing keys: " + ", ".join(missing_keys)
        )

    try:
        north = float(raw_config["north"])
        south = float(raw_config["south"])
        east = float(raw_config["east"])
        west = float(raw_config["west"])
    except (TypeError, ValueError) as error:
        raise ValueError("Bounds config values must be valid numbers.") from error

    if south > north:
        raise ValueError(
            "Bounds config is invalid: south cannot be greater than north."
        )
    if west > east:
        raise ValueError("Bounds config is invalid: west cannot be greater than east.")

    return {
        "north": north,
        "south": south,
        "east": east,
        "west": west,
    }


def to_google_bounds(bounds_config: dict[str, float]) -> dict[str, list[float]]:
    return {
        "northeast": [bounds_config["north"], bounds_config["east"]],
        "southwest": [bounds_config["south"], bounds_config["west"]],
    }


def prompt_for_api_key() -> str:
    api_key = getpass("Google Maps API key (input hidden): ").strip()
    if not api_key:
        raise ValueError("Google Maps API key cannot be blank.")
    return api_key


def normalize_text(value: object, pd_module) -> str:
    if pd_module.isna(value):
        return ""
    return str(value).strip()


def build_address(df, row_index: object, pd_module) -> str:
    line_parts = [
        normalize_text(df.at[row_index, "Address 1"], pd_module),
        normalize_text(df.at[row_index, "Address 2"], pd_module),
        normalize_text(df.at[row_index, "Address 3"], pd_module),
    ]
    location_parts = [
        normalize_text(df.at[row_index, "City"], pd_module),
        normalize_text(df.at[row_index, "State Or Province"], pd_module),
        normalize_text(df.at[row_index, "Postal Code"], pd_module),
    ]

    address_parts = [part for part in line_parts if part]
    location = " ".join(part for part in location_parts if part)
    if location:
        address_parts.append(location)

    return ", ".join(address_parts)


def output_path_for(input_dir: Path) -> Path:
    base_name = "lat-lon-gmaps-api"
    extension = ".csv"

    output_path = input_dir / f"{base_name}{extension}"
    if not output_path.exists():
        return output_path

    append_num = 1
    while True:
        candidate = input_dir / f"{base_name}({append_num}){extension}"
        if not candidate.exists():
            return candidate
        append_num += 1


def create_gmaps_client(api_key: str):
    try:
        import googlemaps
    except ModuleNotFoundError as error:
        missing = error.name or "a required package"
        raise RuntimeError(
            f"Missing dependency: {missing}. "
            "Run 'pip install -r requirements.txt' and try again."
        ) from error

    return googlemaps.Client(key=api_key)


def main() -> int:
    try:
        input_arg, disable_bounds_check, show_help = parse_cli_args(sys.argv)
    except ValueError as error:
        print(f"{error}\n")
        print_usage()
        return 1

    if show_help:
        print_usage()
        return 0

    try:
        input_path = validate_input_path(input_arg)
    except ValueError as error:
        print(f"{error}\n\nExiting...")
        return 1

    bounds_file = Path(__file__).resolve().parent / BOUNDS_CONFIG_FILE
    try:
        bounds_config = load_bounds_config(bounds_file)
    except ValueError as error:
        print(f"{error}\n\nExiting...")
        return 1

    google_bounds = to_google_bounds(bounds_config)

    try:
        df = read_input_file(input_path)
    except Exception as error:
        print(f"Could not read INPUT_FILE: {error}\n\nExiting...")
        return 1

    missing_headers = [
        header for header in REQUIRED_HEADERS if header not in df.columns
    ]
    if missing_headers:
        print("INPUT_FILE is missing required headers:\n")
        for header in missing_headers:
            print(f"- {header}")
        print("\nExiting...")
        return 1

    try:
        api_key = prompt_for_api_key()
    except KeyboardInterrupt:
        print("\nCancelled by user.")
        return 1
    except ValueError as error:
        print(f"{error}\n\nExiting...")
        return 1

    try:
        gmaps = create_gmaps_client(api_key)
    except Exception as error:
        print(f"Could not initialize Google Maps client: {error}\n\nExiting...")
        return 1

    try:
        pd = get_pandas_module()
    except Exception as error:
        print(f"{error}\n\nExiting...")
        return 1

    df["Latitude"] = pd.to_numeric(df["Latitude"], errors="coerce").astype(float)
    df["Longitude"] = pd.to_numeric(df["Longitude"], errors="coerce").astype(float)

    errors = []

    for row_number, row_index in enumerate(df.index, start=2):
        cell_lat = df.at[row_index, "Latitude"]
        cell_lon = df.at[row_index, "Longitude"]

        cell_lat_is_null = pd.isna(cell_lat)
        cell_lon_is_null = pd.isna(cell_lon)
        has_coords = not cell_lat_is_null and not cell_lon_is_null

        address = build_address(df, row_index, pd)

        print("")

        if address == "":
            if has_coords:
                if disable_bounds_check:
                    print(f"Row {row_number} - NO ADDRESS PROVIDED")
                    print(
                        "    "
                        f"{Colors.BLUE}SKIPPING - LAT/LON EXISTS (BOUNDS CHECK DISABLED)"
                        f"{Colors.RESET}"
                    )
                    continue

                if (
                    bounds_config["west"] <= cell_lon <= bounds_config["east"]
                    and bounds_config["south"] <= cell_lat <= bounds_config["north"]
                ):
                    print(f"Row {row_number} - NO ADDRESS PROVIDED")
                    print(
                        f"    {Colors.BLUE}SKIPPING - LAT/LON EXISTS WITHIN BOUNDS{Colors.RESET}"
                    )
                    continue

                print(
                    "Row "
                    f"{row_number} - {Colors.RED}ERROR - LAT/LON EXISTS OUTSIDE BOUNDS "
                    f"- NO FALLBACK ADDRESS{Colors.RESET}"
                )
                print(f"    {Colors.RED}SKIPPING - NO FALLBACK ADDRESS{Colors.RESET}")
                errors.append(
                    f"Row {row_number} - LAT/LON EXISTS OUTSIDE BOUNDS - NO FALLBACK ADDRESS"
                )
                continue

            print(f"Row {row_number} - {Colors.RED}ERROR Nil{Colors.RESET}")
            print(f"    {Colors.RED}SKIPPING - ADDRESS IS EMPTY{Colors.RESET}")
            errors.append(f"Row {row_number} - ADDRESS IS EMPTY")
            continue

        print(f"Row {row_number} - {address}")

        if has_coords:
            if disable_bounds_check:
                print(
                    "    "
                    f"{Colors.BLUE}SKIPPING - LAT/LON EXISTS (BOUNDS CHECK DISABLED)"
                    f"{Colors.RESET}"
                )
                continue

            if (
                bounds_config["west"] <= cell_lon <= bounds_config["east"]
                and bounds_config["south"] <= cell_lat <= bounds_config["north"]
            ):
                print(
                    f"    {Colors.BLUE}SKIPPING - LAT/LON EXISTS WITHIN BOUNDS{Colors.RESET}"
                )
                continue

            print(
                f"    {Colors.YELLOW}RE-EVALUATING - LAT/LON EXISTS OUTSIDE BOUNDS{Colors.RESET}"
            )

        try:
            response = gmaps.geocode(address, bounds=google_bounds)
        except Exception as error:
            print(f"    {Colors.RED}ERROR - GEOCODING FAILED{Colors.RESET}")
            errors.append(f"Row {row_number} - {address} ({error})")
            continue

        if not response:
            print(f"    {Colors.RED}ERROR - ADDRESS NOT READABLE{Colors.RESET}")
            errors.append(f"Row {row_number} - {address}")
            continue

        response_payload = response[0]
        location = response_payload.get("geometry", {}).get("location", {})
        set_lat = location.get("lat")
        set_lon = location.get("lng")

        if set_lat is None or set_lon is None:
            print(f"    {Colors.RED}ERROR - COORDINATES NOT RETURNED{Colors.RESET}")
            errors.append(f"Row {row_number} - {address}")
            continue

        df.at[row_index, "Latitude"] = set_lat
        df.at[row_index, "Longitude"] = set_lon

        print(f"    {Colors.GREEN}GOT COORDS: {set_lat}, {set_lon}{Colors.RESET}")

    save_path = output_path_for(input_path.parent)
    try:
        df.to_csv(save_path)
    except Exception as error:
        print(f"Could not write output CSV: {error}\n\nExiting...")
        return 1

    print("\n")
    if errors:
        print(f"{Colors.RED}{Colors.UNDERLINE}ERRORS{Colors.RESET}")
        print(*errors, sep="\n")
        print("\n")

    print(
        f"{Colors.GREEN}{Colors.BOLD}COMPLETE{Colors.RESET} -- file saved to "
        f"{Colors.BOLD}{Colors.UNDERLINE}{save_path}{Colors.RESET}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
