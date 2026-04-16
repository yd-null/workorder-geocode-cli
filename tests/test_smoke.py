import io
import sys
import unittest
from contextlib import ExitStack, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

try:
    import pandas as pd

    HAS_PANDAS = True
except ModuleNotFoundError:
    pd = None
    HAS_PANDAS = False

import workorder_geocode_cli as cli

try:
    import openpyxl  # noqa: F401

    HAS_OPENPYXL = True
except ModuleNotFoundError:
    HAS_OPENPYXL = False


class FakeGmapsClient:
    def __init__(self):
        self.call_count = 0

    def geocode(self, *_args, **_kwargs):
        self.call_count += 1
        return [{"geometry": {"location": {"lat": -33.8688, "lng": 151.2093}}}]


def sample_dataframe():
    return pd.DataFrame(
        [
            {
                "Address 1": "1 Main St",
                "Address 2": "",
                "Address 3": "",
                "City": "Sydney",
                "State Or Province": "NSW",
                "Postal Code": "2000",
                "Latitude": "-33.8688",
                "Longitude": "151.2093",
            }
        ],
        index=["WO-1"],
    )


class HelpFlagTests(unittest.TestCase):
    def test_short_help_flag_prints_usage_and_flags(self):
        output = io.StringIO()

        with patch.object(sys, "argv", ["workorder-geocode-cli", "-h"]):
            with redirect_stdout(output):
                result = cli.main()

        self.assertEqual(result, 0)
        self.assertIn("Usage:", output.getvalue())
        self.assertIn("-h, --help", output.getvalue())
        self.assertIn("--disable-bounds-check", output.getvalue())

    def test_long_help_flag_prints_usage_and_flags(self):
        output = io.StringIO()

        with patch.object(sys, "argv", ["workorder-geocode-cli", "--help"]):
            with redirect_stdout(output):
                result = cli.main()

        self.assertEqual(result, 0)
        self.assertIn("Usage:", output.getvalue())
        self.assertIn("-h, --help", output.getvalue())
        self.assertIn("--disable-bounds-check", output.getvalue())


@unittest.skipUnless(HAS_PANDAS, "pandas is required for smoke tests")
class SmokeTests(unittest.TestCase):
    def run_main(self, input_path: Path, extra_args=None):
        if extra_args is None:
            extra_args = []

        output = io.StringIO()
        fake_client = FakeGmapsClient()

        with ExitStack() as stack:
            prompt_mock = stack.enter_context(
                patch(
                    "workorder_geocode_cli.prompt_for_api_key", return_value="test-key"
                )
            )
            client_mock = stack.enter_context(
                patch(
                    "workorder_geocode_cli.create_gmaps_client",
                    return_value=fake_client,
                )
            )
            stack.enter_context(
                patch.object(
                    sys,
                    "argv",
                    ["workorder-geocode-cli", *extra_args, str(input_path)],
                )
            )
            stack.enter_context(redirect_stdout(output))
            result = cli.main()

        return result, output.getvalue(), prompt_mock, client_mock, fake_client

    def test_accepts_valid_csv_file(self):
        with TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            input_path = temp_path / "workorders.csv"
            sample_dataframe().to_csv(input_path, index_label="Work Order")

            result, output, prompt_mock, client_mock, fake_client = self.run_main(
                input_path
            )

            self.assertEqual(result, 0)
            self.assertIn("COMPLETE", output)
            self.assertTrue((temp_path / "lat-lon-gmaps-api.csv").exists())
            prompt_mock.assert_called_once()
            client_mock.assert_called_once_with("test-key")
            self.assertEqual(fake_client.call_count, 0)

    @unittest.skipUnless(HAS_OPENPYXL, "openpyxl is required for xlsx smoke test")
    def test_accepts_valid_xlsx_file(self):
        with TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            input_path = temp_path / "workorders.xlsx"
            sample_dataframe().to_excel(input_path, index_label="Work Order")

            result, output, prompt_mock, client_mock, fake_client = self.run_main(
                input_path
            )

            self.assertEqual(result, 0)
            self.assertIn("COMPLETE", output)
            self.assertTrue((temp_path / "lat-lon-gmaps-api.csv").exists())
            prompt_mock.assert_called_once()
            client_mock.assert_called_once_with("test-key")
            self.assertEqual(fake_client.call_count, 0)

    def test_out_of_bounds_existing_coords_are_regeocoded_by_default(self):
        with TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            input_path = temp_path / "out-of-bounds.csv"

            df = sample_dataframe()
            df["Latitude"] = "0"
            df["Longitude"] = "0"
            df.to_csv(input_path, index_label="Work Order")

            result, output, prompt_mock, client_mock, fake_client = self.run_main(
                input_path
            )

            self.assertEqual(result, 0)
            self.assertIn("RE-EVALUATING", output)
            self.assertEqual(fake_client.call_count, 1)
            prompt_mock.assert_called_once()
            client_mock.assert_called_once_with("test-key")

    def test_disable_bounds_check_skips_existing_coords_without_geocoding(self):
        with TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            input_path = temp_path / "out-of-bounds.csv"

            df = sample_dataframe()
            df["Latitude"] = "0"
            df["Longitude"] = "0"
            df.to_csv(input_path, index_label="Work Order")

            result, output, prompt_mock, client_mock, fake_client = self.run_main(
                input_path,
                extra_args=["--disable-bounds-check"],
            )

            self.assertEqual(result, 0)
            self.assertIn("BOUNDS CHECK DISABLED", output)
            self.assertEqual(fake_client.call_count, 0)
            prompt_mock.assert_called_once()
            client_mock.assert_called_once_with("test-key")

    def test_fails_when_required_headers_are_missing(self):
        with TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            input_path = temp_path / "missing-headers.csv"

            df = sample_dataframe().drop(columns=["Longitude"])
            df.to_csv(input_path, index_label="Work Order")

            result, output, prompt_mock, client_mock, fake_client = self.run_main(
                input_path
            )

            self.assertEqual(result, 1)
            self.assertIn("missing required headers", output.lower())
            self.assertIn("- Longitude", output)
            prompt_mock.assert_not_called()
            client_mock.assert_not_called()
            self.assertEqual(fake_client.call_count, 0)

    def test_fails_on_unsupported_extension(self):
        with TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            input_path = temp_path / "workorders.txt"
            input_path.write_text("not a valid input", encoding="utf-8")

            result, output, prompt_mock, client_mock, fake_client = self.run_main(
                input_path
            )

            self.assertEqual(result, 1)
            self.assertIn(".xlsx or .csv", output)
            prompt_mock.assert_not_called()
            client_mock.assert_not_called()
            self.assertEqual(fake_client.call_count, 0)


if __name__ == "__main__":
    unittest.main()
