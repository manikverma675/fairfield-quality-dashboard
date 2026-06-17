import math
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from quality_dashboard.calculations import (
    external_failure_summary,
    filter_ncr_profile,
    ncr_summary,
    scrap_summary,
    scrap_trend,
    weight_summary,
)
from quality_dashboard.config import (
    DEFECT_FILE,
    EXTERNAL_FAILURE_FILE,
    NCR_CASES_FILE,
    SCRAP_FILE,
)
from quality_dashboard.data_loaders import (
    clean_currency,
    load_defect_data,
    load_external_failure_data,
    load_ncr_cases,
    load_scrap_data,
    read_spreadsheetml,
)
from quality_dashboard.metrics import add_period, safe_rate


class DataLoaderUnitTests(unittest.TestCase):
    def test_clean_currency_handles_symbols_commas_and_parentheses(self):
        values = pd.Series(["$1,234.50", "($45.10)", "", None, "0"])
        parsed = clean_currency(values)

        self.assertEqual(parsed.iloc[0], 1234.50)
        self.assertEqual(parsed.iloc[1], -45.10)
        self.assertTrue(pd.isna(parsed.iloc[2]))
        self.assertTrue(pd.isna(parsed.iloc[3]))
        self.assertEqual(parsed.iloc[4], 0)

    def test_read_spreadsheetml_honors_sparse_cell_indexes(self):
        xml = """<?xml version="1.0" encoding="utf-8"?>
        <Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet"
         xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet">
          <Worksheet ss:Name="Cases">
           <Table>
            <Row><Cell><Data ss:Type="String">A</Data></Cell><Cell><Data ss:Type="String">B</Data></Cell><Cell><Data ss:Type="String">C</Data></Cell></Row>
            <Row><Cell><Data ss:Type="String">first</Data></Cell><Cell ss:Index="3"><Data ss:Type="String">third</Data></Cell></Row>
           </Table>
          </Worksheet>
        </Workbook>"""
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "sample.xls"
            path.write_text(xml, encoding="utf-8")
            frame = read_spreadsheetml(path)

        self.assertEqual(frame.loc[0, "A"], "first")
        self.assertEqual(frame.loc[0, "B"], "")
        self.assertEqual(frame.loc[0, "C"], "third")

    def test_safe_rate_returns_nan_for_zero_denominator(self):
        self.assertTrue(math.isnan(safe_rate(10, 0)))
        self.assertEqual(safe_rate(2, 4), 0.5)

    def test_add_period_rejects_unknown_grain(self):
        frame = pd.DataFrame({"Date": pd.to_datetime(["2026-06-11"])})
        with self.assertRaises(ValueError):
            add_period(frame, "Date", "Hourly")

    def test_add_period_supports_yearly_grain(self):
        frame = pd.DataFrame({"Date": pd.to_datetime(["2026-06-11"])})
        yearly = add_period(frame, "Date", "Yearly")

        self.assertEqual(yearly.loc[0, "Period"], pd.Timestamp("2026-01-01"))


class RealFileLoaderTests(unittest.TestCase):
    def test_scrap_loader_keeps_only_confirmed_scrap(self):
        scrap = load_scrap_data(SCRAP_FILE)

        self.assertFalse(scrap.empty)
        self.assertIn("Confirmed Scrap", scrap.columns)

        # Manager's definition: scrap is only negative Inventory Adjustments in quarantine.
        self.assertTrue((scrap["Type"].str.casefold() == "inventory adjustment").all())
        self.assertTrue(scrap["Location"].str.contains("quarantine", case=False).all())
        self.assertTrue((scrap["Quantity"] < 0).all())
        # Inventory Transfers must be excluded entirely.
        self.assertFalse((scrap["Type"].str.casefold() == "inventory transfer").any())
        # Confirmed Scrap is the positive magnitude of the negative quantity.
        self.assertTrue((scrap["Confirmed Scrap"] > 0).all())
        self.assertTrue((scrap["Confirmed Scrap"] == -scrap["Quantity"]).all())

        summary = scrap_summary(scrap, "Confirmed Scrap")
        self.assertGreater(summary["transactions"], 0)
        self.assertGreater(summary["items"], 0)
        self.assertGreater(summary["confirmed_scrap"], 0)
        self.assertEqual(summary["confirmed_scrap"], scrap["Confirmed Scrap"].sum())

        trend = scrap_trend(scrap, "Monthly", "Confirmed Scrap")
        self.assertIn("Confirmed Scrap", trend.columns)
        self.assertFalse(trend.empty)
        self.assertNotEqual(len(scrap_trend(scrap, "Daily", "Confirmed Scrap")), len(trend))

    def test_defect_loader_extracts_actual_weight_measurements(self):
        measurements = load_defect_data(DEFECT_FILE)

        self.assertFalse(measurements.empty)
        self.assertIn("Actual Weight", measurements.columns)
        self.assertIn("Measurement Slot", measurements.columns)
        self.assertIn("Source Row", measurements.columns)
        self.assertNotIn("Defect Rate", measurements.columns)
        self.assertNotIn("Non-Conformity", measurements.columns)
        self.assertGreater(len(measurements), 58)

        summary = weight_summary(measurements)
        self.assertGreater(summary["measurements"], 0)
        self.assertGreater(summary["comparable_measurements"], 0)
        self.assertGreater(summary["items"], 0)
        self.assertGreater(summary["maximum_absolute_variance"], 0)
        self.assertFalse(math.isnan(summary["average_variance"]))

    def test_ncr_loader_supports_ncr_backlog_and_closure_metrics(self):
        cases = load_ncr_cases(NCR_CASES_FILE, as_of=pd.Timestamp("2026-06-11"))
        ncr_cases = filter_ncr_profile(cases, "FPC | NCR")

        self.assertFalse(cases.empty)
        self.assertFalse(ncr_cases.empty)
        self.assertIn("Closure Days", cases.columns)
        self.assertIn("Age Days", cases.columns)

        summary = ncr_summary(ncr_cases)
        self.assertGreater(summary["total"], 0)
        self.assertGreaterEqual(summary["closed"], 0)
        self.assertGreaterEqual(summary["open"], 0)

    def test_external_failure_loader_returns_claim_and_damage_tables(self):
        external = load_external_failure_data(EXTERNAL_FAILURE_FILE)

        self.assertFalse(external.top_claims.empty)
        self.assertFalse(external.department_summary.empty)
        self.assertFalse(external.defective_damaged.empty)
        self.assertIn("Claim Amount", external.top_claims.columns)
        self.assertIn("Total Claim $", external.defective_damaged.columns)

        summary = external_failure_summary(external.top_claims, external.defective_damaged)
        self.assertGreater(summary["total_claims"], 0)
        self.assertGreater(summary["claim_rows"], 0)


if __name__ == "__main__":
    unittest.main()
