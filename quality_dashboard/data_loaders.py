from __future__ import annotations

from dataclasses import dataclass
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pandas as pd

from quality_dashboard.config import (
    DEFECT_FILE,
    EXTERNAL_FAILURE_FILE,
    NCR_CASES_FILE,
    SCRAP_FILE,
)


DATE_COLUMNS = [
    "Incident Date",
    "Date Created",
    "Last Modified",
    "Last Message Date",
    "Date Closed",
    "Last Reopened",
    "Last Message Date.1",
]


@dataclass(frozen=True)
class ExternalFailureData:
    top_claims: pd.DataFrame
    department_summary: pd.DataFrame
    defective_damaged: pd.DataFrame


def make_unique_columns(columns: list[str]) -> list[str]:
    seen: dict[str, int] = {}
    unique: list[str] = []

    for column in columns:
        name = str(column).strip() if column is not None else "Unnamed"
        name = name or "Unnamed"
        if name in seen:
            seen[name] += 1
            name = f"{name}.{seen[name]}"
        else:
            seen[name] = 0
        unique.append(name)

    return unique


def clean_currency(values: pd.Series) -> pd.Series:
    text = values.astype("string").str.strip()
    negative = text.str.match(r"^\(.*\)$", na=False)
    cleaned = (
        text.str.replace(r"[$,()]", "", regex=True)
        .str.strip()
        .replace({"": pd.NA, "nan": pd.NA, "None": pd.NA})
    )
    numeric = pd.to_numeric(cleaned, errors="coerce")
    return numeric.mask(negative, -numeric.abs())


def read_spreadsheetml(path: Path) -> pd.DataFrame:
    ns = {"ss": "urn:schemas-microsoft-com:office:spreadsheet"}
    root = ET.parse(path).getroot()
    rows: list[list[str]] = []

    for row in root.findall(".//ss:Worksheet/ss:Table/ss:Row", ns):
        values: list[str] = []
        column_index = 1

        for cell in row.findall("ss:Cell", ns):
            explicit_index = cell.attrib.get(
                "{urn:schemas-microsoft-com:office:spreadsheet}Index"
            )
            if explicit_index:
                target_index = int(explicit_index)
                while column_index < target_index:
                    values.append("")
                    column_index += 1

            data = cell.find("ss:Data", ns)
            values.append(data.text if data is not None and data.text is not None else "")
            column_index += 1

        rows.append(values)

    if not rows:
        return pd.DataFrame()

    headers = make_unique_columns(rows[0])
    normalized_rows = []
    for row in rows[1:]:
        if len(row) < len(headers):
            row = row + [""] * (len(headers) - len(row))
        normalized_rows.append(row[: len(headers)])

    return pd.DataFrame(normalized_rows, columns=headers)


def load_ncr_cases(path: Path = NCR_CASES_FILE, as_of: pd.Timestamp | None = None) -> pd.DataFrame:
    cases = read_spreadsheetml(path)
    if cases.empty:
        return cases

    text_columns = cases.select_dtypes(include="object").columns
    for column in text_columns:
        cases[column] = cases[column].astype("string").str.strip().fillna("")

    for column in DATE_COLUMNS:
        if column in cases:
            cases[column] = pd.to_datetime(cases[column], errors="coerce")

    as_of = pd.Timestamp.today().normalize() if as_of is None else pd.Timestamp(as_of)
    close_or_as_of = cases["Date Closed"].fillna(as_of)
    cases["Is Open"] = cases["Date Closed"].isna()
    cases["Closure Hours"] = (
        cases["Date Closed"] - cases["Date Created"]
    ).dt.total_seconds() / 3600
    cases["Closure Days"] = cases["Closure Hours"] / 24
    cases["Age Days"] = (close_or_as_of - cases["Date Created"]).dt.total_seconds() / 86400

    return cases


def load_scrap_data(path: Path = SCRAP_FILE) -> pd.DataFrame:
    scrap = pd.read_csv(path)
    scrap["Date"] = pd.to_datetime(scrap["Date"], errors="coerce")
    scrap["Date Created"] = pd.to_datetime(scrap["Date Created"], errors="coerce")
    scrap["Quantity"] = pd.to_numeric(scrap["Quantity"], errors="coerce")

    scrap = scrap.dropna(subset=["Date", "Item", "Quantity"]).copy()
    scrap["Item"] = scrap["Item"].astype(str).str.strip()
    scrap["Into Quarantine"] = scrap["Quantity"].clip(lower=0)
    scrap["Confirmed Scrap"] = -scrap["Quantity"].clip(upper=0)
    scrap["Absolute Movement"] = scrap["Quantity"].abs()
    scrap["Quarantine Balance"] = scrap["Quantity"]
    # Keep legacy aliases so any external code using old names still works
    scrap["Positive Scrap"] = scrap["Into Quarantine"]
    scrap["Net Quantity"] = scrap["Quarantine Balance"]
    return scrap


def load_external_failure_data(
    path: Path = EXTERNAL_FAILURE_FILE,
) -> ExternalFailureData:
    top_claims = pd.read_excel(path, sheet_name="Top Claimed Items")
    top_claims = top_claims.dropna(axis=1, how="all").copy()
    top_claims = top_claims.rename(
        columns={
            "Item description": "Item Description",
            "Item Nbr": "Item Number",
            "Claim Reason Desc": "Claim Reason",
        }
    )
    top_claims["Claim Amount"] = clean_currency(top_claims["Claim $"])
    top_claims["UPC"] = top_claims["UPC"].astype("string")
    top_claims = top_claims[top_claims["Claim Amount"].notna()].copy()

    department_summary = pd.read_excel(path, sheet_name="Department Summary").copy()
    department_summary["Allowance Amount"] = clean_currency(department_summary["Allowances"])
    department_summary["Claim Amount"] = clean_currency(department_summary["Claims"])

    defective_damaged = pd.read_excel(path, sheet_name="Defective & Damaged", header=1)
    defective_damaged = defective_damaged.dropna(axis=1, how="all").copy()
    defective_damaged = defective_damaged.loc[:, ~defective_damaged.columns.str.startswith("Unnamed")]
    defective_damaged = defective_damaged[defective_damaged["UPC"].notna()].copy()

    numeric_columns = [
        "Defective Merch Units",
        "Defective Merch $",
        "Damaged MD to 0 Units",
        "Damaged MD to 0 $",
        "Total Claim $",
        "Total Units",
    ]
    for column in numeric_columns:
        if column in defective_damaged:
            defective_damaged[column] = pd.to_numeric(defective_damaged[column], errors="coerce")

    return ExternalFailureData(
        top_claims=top_claims,
        department_summary=department_summary,
        defective_damaged=defective_damaged,
    )


def parse_report_date(value: object) -> pd.Timestamp | None:
    if not isinstance(value, str) or not value.strip().startswith("Date:"):
        return None
    return pd.to_datetime(value.split(":", 1)[1].strip(), errors="coerce")


def parse_inspector(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip().startswith("Inspector:"):
        return None
    return value.split(":", 1)[1].strip()


def clean_text(value: object) -> str:
    if pd.isna(value):
        return ""
    return str(value).strip()


def parse_weight_spec(value: object) -> dict[str, float | str | bool]:
    raw = clean_text(value)
    if not raw:
        return {"target": float("nan"), "low": float("nan"), "high": float("nan"), "parsed": False}

    normalized = raw.lower().replace("–", "-").replace("—", "-")
    if "none" in normalized or "no work" in normalized:
        return {"target": float("nan"), "low": float("nan"), "high": float("nan"), "parsed": False}

    text_without_spaces = re.sub(r"\s+", "", normalized)
    unit_pattern = r"(?:oz|z|lb|lbs|pnd|pnds|pound|pounds)?"
    range_match = re.fullmatch(
        rf"([-+]?\d+(?:\.\d+)?)-([-+]?\d+(?:\.\d+)?){unit_pattern}",
        text_without_spaces,
    )
    if range_match:
        low, high = sorted([float(range_match.group(1)), float(range_match.group(2))])
        return {"target": (low + high) / 2, "low": low, "high": high, "parsed": True}

    single_match = re.fullmatch(
        rf"([-+]?\d+(?:\.\d+)?){unit_pattern}",
        text_without_spaces,
    )
    if single_match:
        target = float(single_match.group(1))
        return {"target": target, "low": float("nan"), "high": float("nan"), "parsed": True}

    return {"target": float("nan"), "low": float("nan"), "high": float("nan"), "parsed": False}


def comparison_status(actual: float, target: float, low: float, high: float) -> str:
    if pd.notna(low) and pd.notna(high):
        if actual < low:
            return "Below Range"
        if actual > high:
            return "Above Range"
        return "Within Range"
    if pd.isna(target):
        return "Expected Unknown"
    if actual < target:
        return "Below Expected"
    if actual > target:
        return "Above Expected"
    return "At Expected"


def distance_outside_range(actual: float, low: float, high: float) -> float:
    if pd.isna(low) or pd.isna(high):
        return float("nan")
    if actual < low:
        return low - actual
    if actual > high:
        return actual - high
    return 0.0


def load_defect_data(path: Path = DEFECT_FILE) -> pd.DataFrame:
    raw = pd.read_excel(path, sheet_name="Sheet2", header=None)
    records: list[dict[str, object]] = []
    current_date: pd.Timestamp | None = None
    current_inspector: str | None = None
    current_item = ""
    current_work_order = ""
    current_expected_1 = ""
    current_expected_2 = ""
    current_tolerance = ""

    for source_index, row in raw.iterrows():
        first = row.iloc[0]
        third = row.iloc[2] if len(row) > 2 else None

        parsed_date = parse_report_date(first)
        if parsed_date is not None:
            current_date = parsed_date
            parsed_inspector = parse_inspector(third)
            if parsed_inspector:
                current_inspector = parsed_inspector
            current_item = ""
            current_work_order = ""
            current_expected_1 = ""
            current_expected_2 = ""
            current_tolerance = ""
            continue

        if first == "Assembly Item" or pd.isna(first):
            item_cell = ""
        else:
            item_cell = clean_text(first)

        work_order_cell = clean_text(row.iloc[1])
        expected_1_cell = clean_text(row.iloc[2])
        expected_2_cell = clean_text(row.iloc[3])
        tolerance_cell = clean_text(row.iloc[8]) if len(row) > 8 else ""

        if item_cell:
            current_item = item_cell
            if work_order_cell:
                current_work_order = work_order_cell
            current_expected_1 = expected_1_cell
            current_expected_2 = expected_2_cell
            current_tolerance = tolerance_cell

        if not current_item:
            continue

        actual_values = [
            ("Actual Weight 1", row.iloc[4], current_expected_1),
            ("Actual Weight 2", row.iloc[5], current_expected_2 or current_expected_1),
        ]
        for measurement_slot, raw_weight, expected_text in actual_values:
            actual_weight = pd.to_numeric(raw_weight, errors="coerce")
            if pd.isna(actual_weight):
                continue
            actual_weight = float(actual_weight)
            expected_spec = parse_weight_spec(expected_text)
            tolerance_spec = parse_weight_spec(current_tolerance)
            expected_low = expected_spec["low"]
            expected_high = expected_spec["high"]
            tolerance_low = tolerance_spec["low"]
            tolerance_high = tolerance_spec["high"]
            comparison_low = tolerance_low if pd.notna(tolerance_low) else expected_low
            comparison_high = tolerance_high if pd.notna(tolerance_high) else expected_high
            target = expected_spec["target"]
            variance = actual_weight - target if pd.notna(target) else float("nan")

            records.append(
                {
                    "Date": current_date,
                    "Inspector": current_inspector or "",
                    "Assembly Item": current_item,
                    "Work Order": current_work_order,
                    "Expected Weight 1": current_expected_1,
                    "Expected Weight 2": current_expected_2,
                    "Expected Weight": expected_text,
                    "Expected Target": target,
                    "Expected Low": expected_low,
                    "Expected High": expected_high,
                    "Tolerance Low": tolerance_low,
                    "Tolerance High": tolerance_high,
                    "Comparison Low": comparison_low,
                    "Comparison High": comparison_high,
                    "Actual Weight": actual_weight,
                    "Variance": variance,
                    "Absolute Variance": abs(variance) if pd.notna(variance) else float("nan"),
                    "Variance Percent": variance / target if pd.notna(target) and target != 0 else float("nan"),
                    "Distance Outside Range": distance_outside_range(
                        actual_weight, comparison_low, comparison_high
                    ),
                    "Weight Status": comparison_status(
                        actual_weight, target, comparison_low, comparison_high
                    ),
                    "Expected Parsed": bool(expected_spec["parsed"]),
                    "Measurement Slot": measurement_slot,
                    "Tolerance": current_tolerance,
                    "Source Row": int(source_index) + 1,
                }
            )

    defects = pd.DataFrame(records)
    if not defects.empty:
        defects["Date"] = pd.to_datetime(defects["Date"], errors="coerce")
    return defects


def extract_report_range_from_filename(path: Path) -> tuple[pd.Timestamp | None, pd.Timestamp | None]:
    matches = re.findall(r"\d{4}-\d{2}-\d{2}", path.name)
    if len(matches) < 2:
        return None, None
    return pd.to_datetime(matches[0]), pd.to_datetime(matches[1])
