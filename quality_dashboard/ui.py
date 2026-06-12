import altair as alt
import pandas as pd
import streamlit as st


CHART_BLUE = "#2563eb"
CHART_TEAL = "#0f766e"
CHART_GREEN = "#3f7d20"
CHART_ORANGE = "#d97706"
CHART_RED = "#b91c1c"
CHART_GRAY = "#64748b"


def configure_page(title: str) -> None:
    st.set_page_config(page_title=title, layout="wide")
    apply_theme()


def apply_theme() -> None:
    st.markdown(
        """
        <style>
        .stApp {
            background: #fafaf9;
            color: #1c1917;
        }
        section[data-testid="stSidebar"] {
            background: #f5f5f4;
            border-right: 1px solid #e7e5e4;
        }
        div[data-testid="stMetric"] {
            background: #ffffff;
            border: 1px solid #e7e5e4;
            border-radius: 8px;
            padding: 14px 16px;
            box-shadow: 0 1px 2px rgba(28, 25, 23, 0.05);
        }
        div[data-testid="stMetric"] label {
            color: #78716c;
        }
        h1, h2, h3 {
            letter-spacing: 0;
        }
        div[data-testid="stDataFrame"] {
            border: 1px solid #e7e5e4;
            border-radius: 8px;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_header(title: str, subtitle: str, source: str) -> None:
    st.title(title)
    st.caption(f"{subtitle} Source: {source}")


def file_missing(path) -> None:
    st.error(f"Required data file not found: {path}")
    st.stop()


def bar_chart(
    data: pd.DataFrame,
    x_col: str,
    y_col: str,
    title: str,
    *,
    color: str = CHART_BLUE,
    x_format: str | None = None,
    selectable: bool = False,
) -> alt.Chart:
    x_axis = alt.Axis(format=x_format) if x_format else alt.Axis()
    tooltip = [
        alt.Tooltip(f"{y_col}:N", title=y_col),
        alt.Tooltip(f"{x_col}:Q", title=x_col, format=x_format or ",.2f"),
    ]
    chart = (
        alt.Chart(data)
        .mark_bar(color=color)
        .encode(
            x=alt.X(f"{x_col}:Q", title=x_col, axis=x_axis),
            y=alt.Y(
                f"{y_col}:N",
                title=None,
                sort="-x",
                axis=alt.Axis(labelLimit=0, labelFontSize=11),
            ),
            tooltip=tooltip,
        )
        .properties(title=title, height=max(280, min(620, 30 * max(len(data), 1))))
    )
    if selectable:
        sel = alt.selection_point(name="sel", fields=[y_col])
        chart = chart.add_params(sel).encode(
            opacity=alt.condition(sel, alt.value(1.0), alt.value(0.4))
        )
    return chart


def period_line_chart(
    data: pd.DataFrame,
    y_col: str,
    title: str,
    *,
    color: str = CHART_BLUE,
    y_format: str | None = None,
    extra_tooltips: list[alt.Tooltip] | None = None,
    height: int = 340,
) -> alt.Chart:
    y_axis = alt.Axis(format=y_format) if y_format else alt.Axis()
    tooltips = [
        alt.Tooltip("Period:T", title="Period"),
        alt.Tooltip(f"{y_col}:Q", title=y_col, format=y_format or ",.2f"),
    ]
    if extra_tooltips:
        tooltips.extend(extra_tooltips)

    return (
        alt.Chart(data)
        .mark_line(point=True, color=color, strokeWidth=3)
        .encode(
            x=alt.X("Period:T", title=None),
            y=alt.Y(f"{y_col}:Q", title=y_col, axis=y_axis),
            tooltip=tooltips,
        )
        .properties(title=title, height=height)
    )


def dual_line_chart(
    data: pd.DataFrame,
    series_cols: list[str],
    title: str,
    *,
    colors: list[str] | None = None,
) -> alt.Chart:
    palette = colors or [CHART_BLUE, CHART_ORANGE, CHART_TEAL, CHART_RED]
    melted = data.melt(id_vars="Period", value_vars=series_cols, var_name="Series", value_name="Value")
    color_scale = alt.Scale(domain=series_cols, range=palette[: len(series_cols)])
    return (
        alt.Chart(melted)
        .mark_line(point=True, strokeWidth=2.5)
        .encode(
            x=alt.X("Period:T", title=None),
            y=alt.Y("Value:Q", title="Cases"),
            color=alt.Color("Series:N", scale=color_scale, legend=alt.Legend(orient="bottom")),
            tooltip=[
                alt.Tooltip("Period:T", title="Period"),
                alt.Tooltip("Series:N", title="Series"),
                alt.Tooltip("Value:Q", title="Cases", format=","),
            ],
        )
        .properties(title=title, height=340)
    )


def empty_state(message: str) -> None:
    st.warning(message)
    st.stop()


def selected_value(event, field: str):
    """Return the value of `field` for the bar a user clicked, or None if nothing is selected.

    Works with the event object returned by st.altair_chart(..., on_select="rerun")
    when the chart was built with bar_chart(selectable=True).
    """
    try:
        points = event.selection.get("sel", [])
        if points:
            return points[0].get(field)
    except (AttributeError, KeyError, TypeError, IndexError):
        return None
    return None
