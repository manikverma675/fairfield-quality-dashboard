import pandas as pd


PERIOD_OPTIONS = ["Daily", "Weekly", "Monthly", "Quarterly", "Yearly"]


def add_period(df: pd.DataFrame, date_col: str, grain: str) -> pd.DataFrame:
    framed = df.copy()
    dates = pd.to_datetime(framed[date_col], errors="coerce")

    if grain == "Daily":
        framed["Period"] = dates.dt.floor("D")
    elif grain == "Weekly":
        framed["Period"] = dates.dt.to_period("W-SUN").dt.start_time
    elif grain == "Monthly":
        framed["Period"] = dates.dt.to_period("M").dt.to_timestamp()
    elif grain == "Quarterly":
        framed["Period"] = dates.dt.to_period("Q").dt.to_timestamp()
    elif grain == "Yearly":
        framed["Period"] = dates.dt.to_period("Y").dt.to_timestamp()
    else:
        raise ValueError(f"Unsupported period grain: {grain}")

    return framed


def safe_rate(numerator: float, denominator: float) -> float:
    if pd.isna(denominator) or denominator == 0:
        return float("nan")
    return numerator / denominator


def pct_change_text(current: float, previous: float, *, decimals: int = 1) -> str:
    if pd.isna(previous):
        return "No prior period"

    delta = current - previous
    if previous == 0:
        return f"{delta:,.0f} vs prior"
    return f"{delta:,.0f} ({delta / abs(previous):.{decimals}%}) vs prior"


def format_number(value: float) -> str:
    if pd.isna(value):
        return "-"
    return f"{value:,.0f}" if abs(value) >= 10 else f"{value:,.2f}".rstrip("0").rstrip(".")


def format_currency(value: float) -> str:
    if pd.isna(value):
        return "-"
    return f"${value:,.0f}"


def format_currency_short(value: float) -> str:
    if pd.isna(value):
        return "-"
    abs_val = abs(value)
    sign = "-" if value < 0 else ""
    if abs_val >= 1_000_000:
        return f"{sign}${abs_val / 1_000_000:.1f}M"
    if abs_val >= 1_000:
        return f"{sign}${abs_val / 1_000:.1f}K"
    return f"{sign}${abs_val:,.0f}"


def format_percent(value: float) -> str:
    if pd.isna(value):
        return "-"
    return f"{value:.1%}"


def date_bounds(df: pd.DataFrame, date_col: str) -> tuple:
    dates = pd.to_datetime(df[date_col], errors="coerce").dropna()
    if dates.empty:
        return None, None
    return dates.min().date(), dates.max().date()
