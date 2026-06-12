from __future__ import annotations

import pandas as pd

from quality_dashboard.config import CLOSED_STAGE, OPEN_STATUSES
from quality_dashboard.metrics import add_period


def filter_by_date(
    df: pd.DataFrame,
    date_col: str,
    start_date,
    end_date,
) -> pd.DataFrame:
    if df.empty or date_col not in df:
        return df.copy()

    dates = pd.to_datetime(df[date_col], errors="coerce")
    filtered = df.copy()
    if start_date is not None:
        filtered = filtered[dates.dt.date >= start_date]
    if end_date is not None:
        filtered = filtered[dates.dt.date <= end_date]
    return filtered.copy()


def filter_ncr_profile(cases: pd.DataFrame, profile: str) -> pd.DataFrame:
    if cases.empty or "Profile" not in cases:
        return pd.DataFrame(columns=cases.columns)
    return cases[cases["Profile"].eq(profile)].copy()


def filter_complaints(cases: pd.DataFrame) -> pd.DataFrame:
    if cases.empty:
        return pd.DataFrame(columns=cases.columns)
    mask = cases["Profile"].eq("FPC | NCR") & cases["Assigned To"].eq("Sheri King")
    return cases[mask].copy()


def ncr_summary(cases: pd.DataFrame) -> dict[str, float]:
    if cases.empty:
        return {
            "total": 0,
            "open": 0,
            "closed": 0,
            "median_closure_days": float("nan"),
            "avg_age_days": float("nan"),
        }

    is_closed = cases.get("Stage", pd.Series(dtype=str)).eq(CLOSED_STAGE)
    is_open = cases["Status"].isin(OPEN_STATUSES)
    closed = cases[is_closed & cases["Date Closed"].notna()]
    return {
        "total": int(len(cases)),
        "open": int(is_open.sum()),
        "closed": int(is_closed.sum()),
        "median_closure_days": closed["Closure Days"].median(),
        "avg_age_days": cases[is_open]["Age Days"].mean(),
    }


def ncr_created_trend(cases: pd.DataFrame, grain: str) -> pd.DataFrame:
    if cases.empty:
        return pd.DataFrame(columns=["Period", "Created Cases", "Open Cases", "Closed Cases"])

    framed = add_period(cases.dropna(subset=["Date Created"]), "Date Created", grain)
    if framed.empty:
        return pd.DataFrame(columns=["Period", "Created Cases", "Open Cases", "Closed Cases"])

    trend = (
        framed.groupby("Period", as_index=False)
        .agg(
            **{
                "Created Cases": ("Number", "count"),
                "Open Cases": ("Status", lambda s: s.isin(OPEN_STATUSES).sum()),
                "Closed Cases": ("Stage", lambda s: s.eq(CLOSED_STAGE).sum()),
            }
        )
        .sort_values("Period")
    )
    return trend


def ncr_status_trend(cases: pd.DataFrame, grain: str) -> pd.DataFrame:
    """Cases created per period broken down by current Status — one row per (Period, Status)."""
    if cases.empty:
        return pd.DataFrame(columns=["Period", "Status", "Cases"])

    framed = add_period(cases.dropna(subset=["Date Created"]), "Date Created", grain)
    if framed.empty:
        return pd.DataFrame(columns=["Period", "Status", "Cases"])

    return (
        framed.groupby(["Period", "Status"], as_index=False)
        .agg(Cases=("Number", "count"))
        .sort_values(["Period", "Status"])
    )


def ncr_closure_trend(cases: pd.DataFrame, grain: str) -> pd.DataFrame:
    closed = cases[
        cases.get("Stage", pd.Series(dtype=str)).eq(CLOSED_STAGE) & cases["Date Closed"].notna()
    ].dropna(subset=["Closure Days"]).copy()
    if closed.empty:
        return pd.DataFrame(columns=["Period", "Closed Cases", "Median Closure Days", "Average Closure Days"])

    framed = add_period(closed, "Date Closed", grain)
    return (
        framed.groupby("Period", as_index=False)
        .agg(
            **{
                "Closed Cases": ("Number", "count"),
                "Median Closure Days": ("Closure Days", "median"),
                "Average Closure Days": ("Closure Days", "mean"),
            }
        )
        .sort_values("Period")
    )


def ncr_status_summary(cases: pd.DataFrame) -> pd.DataFrame:
    if cases.empty:
        return pd.DataFrame(columns=["Status", "Cases"])
    return cases.groupby("Status", as_index=False).agg(Cases=("Number", "count")).sort_values(
        "Cases", ascending=False
    )


def ncr_company_summary(cases: pd.DataFrame, limit: int | None = 15) -> pd.DataFrame:
    if cases.empty:
        return pd.DataFrame(columns=["Company", "Cases", "Open Cases"])
    result = (
        cases.groupby("Company", as_index=False)
        .agg(
            **{
                "Cases": ("Number", "count"),
                "Open Cases": ("Date Closed", lambda values: values.isna().sum()),
            }
        )
        .sort_values("Cases", ascending=False)
    )
    return result if limit is None else result.head(limit)


def open_case_aging(cases: pd.DataFrame) -> pd.DataFrame:
    open_cases = cases[cases["Status"].isin(OPEN_STATUSES)].copy()
    if open_cases.empty:
        return pd.DataFrame(columns=["Age Bucket", "Cases"])

    bins = [-1, 7, 30, 60, 90, 180, float("inf")]
    labels = ["0-7", "8-30", "31-60", "61-90", "91-180", "181+"]
    open_cases["Age Bucket"] = pd.cut(open_cases["Age Days"], bins=bins, labels=labels)
    return (
        open_cases.groupby("Age Bucket", observed=False)
        .size()
        .reset_index(name="Cases")
    )


def scrap_summary(scrap: pd.DataFrame, measure_col: str) -> dict[str, float]:
    if scrap.empty:
        return {
            "measure_total": 0,
            "transactions": 0,
            "items": 0,
            "quarantine_balance": 0,
            "into_quarantine": 0,
            "confirmed_scrap": 0,
            "absolute_movement": 0,
        }

    return {
        "measure_total": scrap[measure_col].sum(),
        "transactions": int(len(scrap)),
        "items": int(scrap["Item"].nunique()),
        "quarantine_balance": scrap["Quarantine Balance"].sum(),
        "into_quarantine": scrap["Into Quarantine"].sum(),
        "confirmed_scrap": scrap["Confirmed Scrap"].sum(),
        "absolute_movement": scrap["Absolute Movement"].sum(),
    }


def scrap_trend(scrap: pd.DataFrame, grain: str, measure_col: str) -> pd.DataFrame:
    if scrap.empty:
        return pd.DataFrame(columns=["Period", measure_col, "Transactions", "Items", "Rolling Average"])

    framed = add_period(scrap, "Date", grain)
    trend = (
        framed.groupby("Period", as_index=False)
        .agg(
            **{
                measure_col: (measure_col, "sum"),
                "Transactions": ("Id", "count"),
                "Items": ("Item", "nunique"),
            }
        )
        .sort_values("Period")
    )
    trend["Rolling Average"] = trend[measure_col].rolling(window=4, min_periods=1).mean()
    return trend


def scrap_rate_trend(scrap: pd.DataFrame, grain: str) -> pd.DataFrame:
    if scrap.empty:
        return pd.DataFrame(
            columns=[
                "Period",
                "Confirmed Scrap",
                "Into Quarantine",
                "Quarantine Balance",
                "Scrap Confirmation Rate",
                "Transactions",
            ]
        )

    framed = add_period(scrap, "Date", grain)
    trend = (
        framed.groupby("Period", as_index=False)
        .agg(
            **{
                "Confirmed Scrap": ("Confirmed Scrap", "sum"),
                "Into Quarantine": ("Into Quarantine", "sum"),
                "Quarantine Balance": ("Quarantine Balance", "sum"),
                "Transactions": ("Id", "count"),
            }
        )
        .sort_values("Period")
    )
    denominator = trend["Into Quarantine"].replace({0: pd.NA})
    trend["Scrap Confirmation Rate"] = trend["Confirmed Scrap"] / denominator
    return trend


def scrap_item_summary(scrap: pd.DataFrame, measure_col: str, limit: int | None = 15) -> pd.DataFrame:
    if scrap.empty:
        return pd.DataFrame(columns=["Item", measure_col, "Transactions", "First Date", "Last Date"])

    result = (
        scrap.groupby("Item", as_index=False)
        .agg(
            **{
                measure_col: (measure_col, "sum"),
                "Transactions": ("Id", "count"),
                "First Date": ("Date", "min"),
                "Last Date": ("Date", "max"),
            }
        )
        .sort_values(measure_col, ascending=False)
    )
    return result if limit is None else result.head(limit)


def scrap_item_trend(
    scrap: pd.DataFrame,
    grain: str,
    measure_col: str,
    items: list[str],
) -> pd.DataFrame:
    if scrap.empty or not items:
        return pd.DataFrame(columns=["Period", "Item", measure_col, "Transactions"])

    framed = add_period(scrap[scrap["Item"].isin(items)], "Date", grain)
    return (
        framed.groupby(["Period", "Item"], as_index=False)
        .agg(**{measure_col: (measure_col, "sum"), "Transactions": ("Id", "count")})
        .sort_values(["Period", "Item"])
    )


def weight_summary(measurements: pd.DataFrame) -> dict[str, float]:
    if measurements.empty:
        return {
            "measurements": 0,
            "comparable_measurements": 0,
            "items": 0,
            "work_orders": 0,
            "average_variance": float("nan"),
            "average_absolute_variance": float("nan"),
            "maximum_absolute_variance": float("nan"),
            "within_range": 0,
            "below_expected": 0,
            "above_expected": 0,
            "expected_unknown": 0,
        }

    comparable = measurements[measurements["Expected Target"].notna()].copy()
    return {
        "measurements": int(len(measurements)),
        "comparable_measurements": int(len(comparable)),
        "items": int(measurements["Assembly Item"].nunique()),
        "work_orders": int(measurements["Work Order"].replace("", pd.NA).nunique()),
        "average_variance": comparable["Variance"].mean(),
        "average_absolute_variance": comparable["Absolute Variance"].mean(),
        "maximum_absolute_variance": comparable["Absolute Variance"].max(),
        "within_range": int(measurements["Weight Status"].eq("Within Range").sum()),
        "below_expected": int(measurements["Weight Status"].isin(["Below Range", "Below Expected"]).sum()),
        "above_expected": int(measurements["Weight Status"].isin(["Above Range", "Above Expected"]).sum()),
        "expected_unknown": int(measurements["Weight Status"].eq("Expected Unknown").sum()),
    }


def weight_trend(measurements: pd.DataFrame, grain: str) -> pd.DataFrame:
    clean = measurements.dropna(subset=["Date", "Expected Target", "Variance"]).copy()
    if clean.empty:
        return pd.DataFrame(
            columns=[
                "Period",
                "Comparable Measurements",
                "Average Variance",
                "Average Absolute Variance",
                "Maximum Absolute Variance",
            ]
        )

    framed = add_period(clean, "Date", grain)
    return (
        framed.groupby("Period", as_index=False)
        .agg(
            **{
                "Comparable Measurements": ("Actual Weight", "count"),
                "Average Variance": ("Variance", "mean"),
                "Average Absolute Variance": ("Absolute Variance", "mean"),
                "Maximum Absolute Variance": ("Absolute Variance", "max"),
            }
        )
        .sort_values("Period")
    )


def weight_item_summary(measurements: pd.DataFrame, limit: int | None = 15) -> pd.DataFrame:
    if measurements.empty:
        return pd.DataFrame(
            columns=[
                "Assembly Item",
                "Measurements",
                "Comparable Measurements",
                "Work Orders",
                "Average Variance",
                "Average Absolute Variance",
                "Maximum Absolute Variance",
                "Within Range",
                "Below Expected",
                "Above Expected",
                "Expected Unknown",
            ]
        )

    summary = (
        measurements.groupby("Assembly Item", as_index=False)
        .agg(
            **{
                "Measurements": ("Actual Weight", "count"),
                "Comparable Measurements": ("Expected Target", lambda values: values.notna().sum()),
                "Work Orders": ("Work Order", lambda values: values.replace("", pd.NA).nunique()),
                "Average Variance": ("Variance", "mean"),
                "Average Absolute Variance": ("Absolute Variance", "mean"),
                "Maximum Absolute Variance": ("Absolute Variance", "max"),
                "Within Range": ("Weight Status", lambda values: values.eq("Within Range").sum()),
                "Below Expected": (
                    "Weight Status",
                    lambda values: values.isin(["Below Range", "Below Expected"]).sum(),
                ),
                "Above Expected": (
                    "Weight Status",
                    lambda values: values.isin(["Above Range", "Above Expected"]).sum(),
                ),
                "Expected Unknown": ("Weight Status", lambda values: values.eq("Expected Unknown").sum()),
            }
        )
    )
    summary = summary.sort_values(
        ["Average Absolute Variance", "Comparable Measurements"],
        ascending=[False, False],
        na_position="last",
    )
    return summary if limit is None else summary.head(limit)


def weight_work_order_summary(measurements: pd.DataFrame, limit: int | None = 50) -> pd.DataFrame:
    if measurements.empty:
        return pd.DataFrame(
            columns=[
                "Assembly Item",
                "Work Order",
                "Expected Weight 1",
                "Expected Weight 2",
                "Tolerance",
                "Measurements",
                "Comparable Measurements",
                "Average Variance",
                "Average Absolute Variance",
                "Maximum Absolute Variance",
                "Within Range",
                "Below Expected",
                "Above Expected",
                "Expected Unknown",
            ]
        )

    grouped = (
        measurements.groupby(
            ["Assembly Item", "Work Order", "Expected Weight 1", "Expected Weight 2", "Tolerance"],
            dropna=False,
            as_index=False,
        )
        .agg(
            **{
                "Measurements": ("Actual Weight", "count"),
                "Comparable Measurements": ("Expected Target", lambda values: values.notna().sum()),
                "Average Variance": ("Variance", "mean"),
                "Average Absolute Variance": ("Absolute Variance", "mean"),
                "Maximum Absolute Variance": ("Absolute Variance", "max"),
                "Within Range": ("Weight Status", lambda values: values.eq("Within Range").sum()),
                "Below Expected": (
                    "Weight Status",
                    lambda values: values.isin(["Below Range", "Below Expected"]).sum(),
                ),
                "Above Expected": (
                    "Weight Status",
                    lambda values: values.isin(["Above Range", "Above Expected"]).sum(),
                ),
                "Expected Unknown": ("Weight Status", lambda values: values.eq("Expected Unknown").sum()),
            }
        )
        .sort_values(
            ["Average Absolute Variance", "Comparable Measurements", "Assembly Item"],
            ascending=[False, False, True],
            na_position="last",
        )
    )
    return grouped if limit is None else grouped.head(limit)


def weight_inspector_summary(measurements: pd.DataFrame) -> pd.DataFrame:
    if measurements.empty:
        return pd.DataFrame(
            columns=[
                "Inspector",
                "Measurements",
                "Comparable Measurements",
                "Average Variance",
                "Average Absolute Variance",
                "Maximum Absolute Variance",
            ]
        )

    return (
        measurements.groupby("Inspector", as_index=False)
        .agg(
            **{
                "Measurements": ("Actual Weight", "count"),
                "Comparable Measurements": ("Expected Target", lambda values: values.notna().sum()),
                "Average Variance": ("Variance", "mean"),
                "Average Absolute Variance": ("Absolute Variance", "mean"),
                "Maximum Absolute Variance": ("Absolute Variance", "max"),
            }
        )
        .sort_values(
            ["Average Absolute Variance", "Comparable Measurements"],
            ascending=[False, False],
            na_position="last",
        )
    )


_DEFECT_DAMAGE_REASONS = {"Defective Merchandise", "Damaged MD to 0"}


def external_failure_summary(top_claims: pd.DataFrame) -> dict[str, float]:
    if top_claims.empty:
        return {
            "total_claims": 0,
            "claim_rows": 0,
            "unique_items": 0,
            "defect_damage_cost": 0,
            "defect_damage_units": 0,
        }

    dd = top_claims[top_claims["Claim Reason"].isin(_DEFECT_DAMAGE_REASONS)]
    return {
        "total_claims": top_claims["Claim Amount"].sum(),
        "claim_rows": int(len(top_claims)),
        "unique_items": int(top_claims["UPC"].nunique()),
        "defect_damage_cost": dd["Claim Amount"].sum(),
        "defect_damage_units": int(len(dd)),
    }


def claims_by_reason(top_claims: pd.DataFrame) -> pd.DataFrame:
    if top_claims.empty:
        return pd.DataFrame(columns=["Claim Reason", "Claims", "Claim Amount"])
    return (
        top_claims.groupby("Claim Reason", as_index=False)
        .agg(**{"Claims": ("UPC", "count"), "Claim Amount": ("Claim Amount", "sum")})
        .sort_values("Claim Amount", ascending=False)
    )


def claims_by_item(top_claims: pd.DataFrame, limit: int | None = 15) -> pd.DataFrame:
    if top_claims.empty:
        return pd.DataFrame(columns=["Item Description", "Claims", "Claim Amount"])
    result = (
        top_claims.groupby("Item Description", as_index=False)
        .agg(**{"Claims": ("UPC", "count"), "Claim Amount": ("Claim Amount", "sum")})
        .sort_values("Claim Amount", ascending=False)
    )
    return result if limit is None else result.head(limit)
