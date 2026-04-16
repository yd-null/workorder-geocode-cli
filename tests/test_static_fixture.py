import io
import sys
import unittest
from contextlib import ExitStack, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import workorder_geocode_cli as cli

try:
    import pandas as pd

    HAS_PANDAS = True
except ModuleNotFoundError:
    pd = None
    HAS_PANDAS = False


FIXTURE_PATH = (
    Path(__file__).resolve().parent.parent / "synthetic_work_orders_sample.xlsx"
)
LOCKED_BOUNDS = {"north": -8.0, "south": -45.0, "east": 156.0, "west": 104.0}


class FakeGmapsClient:
    def __init__(self):
        self.call_count = 0

    def geocode(self, *_args, **_kwargs):
        self.call_count += 1
        return [{"geometry": {"location": {"lat": -33.8688, "lng": 151.2093}}}]


@unittest.skipUnless(HAS_PANDAS, "pandas is required for static fixture tests")
@unittest.skipUnless(FIXTURE_PATH.exists(), "synthetic fixture file is required")
class StaticFixtureTests(unittest.TestCase):
    def classify_rows(self, df):
        def has_text(value):
            if pd.isna(value):
                return False
            return str(value).strip() != ""

        lat_text = df["Latitude"].apply(has_text)
        lon_text = df["Longitude"].apply(has_text)

        lat_num = pd.to_numeric(df["Latitude"], errors="coerce")
        lon_num = pd.to_numeric(df["Longitude"], errors="coerce")
        has_numeric_coords = lat_num.notna() & lon_num.notna()

        addr_cols = [
            "Address 1",
            "Address 2",
            "Address 3",
            "City",
            "State Or Province",
            "Postal Code",
        ]
        has_address = (
            df[addr_cols]
            .fillna("")
            .apply(lambda row: any(str(value).strip() for value in row), axis=1)
        )

        in_bounds = (
            has_numeric_coords
            & lon_num.between(104.0, 156.0)
            & lat_num.between(-45.0, -8.0)
        )

        categories = {
            "coords_only": lat_text & lon_text & ~has_address,
            "address_only": ~lat_text & ~lon_text & has_address,
            "out_of_bounds_with_address": has_numeric_coords & has_address & ~in_bounds,
            "in_bounds_with_address": in_bounds & has_address,
            "partial_coords": lat_text ^ lon_text,
            "invalid_coord_text": lat_text & lon_text & ~has_numeric_coords,
            "empty_address": ~has_address,
        }
        return categories

    def run_main(self, extra_args=None):
        if extra_args is None:
            extra_args = []

        output_buffer = io.StringIO()
        fake_client = FakeGmapsClient()

        with TemporaryDirectory() as temp_dir:
            temp_output = Path(temp_dir) / "fixture-output.csv"
            with ExitStack() as stack:
                stack.enter_context(
                    patch(
                        "workorder_geocode_cli.prompt_for_api_key",
                        return_value="test-key",
                    )
                )
                stack.enter_context(
                    patch(
                        "workorder_geocode_cli.create_gmaps_client",
                        return_value=fake_client,
                    )
                )
                stack.enter_context(
                    patch(
                        "workorder_geocode_cli.load_bounds_config",
                        return_value=LOCKED_BOUNDS,
                    )
                )
                stack.enter_context(
                    patch(
                        "workorder_geocode_cli.output_path_for",
                        return_value=temp_output,
                    )
                )
                stack.enter_context(
                    patch.object(
                        sys,
                        "argv",
                        ["workorder-geocode-cli", *extra_args, str(FIXTURE_PATH)],
                    )
                )
                stack.enter_context(redirect_stdout(output_buffer))
                result = cli.main()

            wrote_output = temp_output.exists()

        return result, output_buffer.getvalue(), fake_client.call_count, wrote_output

    def test_fixture_has_expected_mutation_mix(self):
        df = pd.read_excel(
            FIXTURE_PATH, sheet_name="Completed Work Orders FY Filter", dtype=str
        )
        categories = self.classify_rows(df)

        self.assertEqual(len(df), 10)
        self.assertEqual(int(categories["coords_only"].sum()), 2)
        self.assertEqual(int(categories["address_only"].sum()), 2)
        self.assertEqual(int(categories["out_of_bounds_with_address"].sum()), 2)
        self.assertEqual(int(categories["in_bounds_with_address"].sum()), 1)
        self.assertEqual(int(categories["partial_coords"].sum()), 1)
        self.assertEqual(int(categories["invalid_coord_text"].sum()), 1)
        self.assertEqual(int(categories["empty_address"].sum()), 3)

        self.assertTrue(df["Work Order Number"].is_unique)

    def test_default_mode_hits_expected_paths(self):
        result, output, geocode_calls, wrote_output = self.run_main()

        self.assertEqual(result, 0)
        self.assertTrue(wrote_output)
        self.assertEqual(geocode_calls, 6)
        self.assertIn("SKIPPING - LAT/LON EXISTS WITHIN BOUNDS", output)
        self.assertIn("RE-EVALUATING - LAT/LON EXISTS OUTSIDE BOUNDS", output)
        self.assertIn("ERROR - ADDRESS IS EMPTY", output)

    def test_disable_bounds_check_skips_existing_coords_without_geocoding(self):
        result, output, geocode_calls, wrote_output = self.run_main(
            extra_args=["--disable-bounds-check"]
        )

        self.assertEqual(result, 0)
        self.assertTrue(wrote_output)
        self.assertEqual(geocode_calls, 4)
        self.assertEqual(output.count("BOUNDS CHECK DISABLED"), 3)
        self.assertNotIn("RE-EVALUATING - LAT/LON EXISTS OUTSIDE BOUNDS", output)


if __name__ == "__main__":
    unittest.main()
