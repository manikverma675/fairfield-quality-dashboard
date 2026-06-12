"""Agentic quality-data assistant.

Instead of pasting pre-computed summaries into the prompt, this gives the LLM a
read-only SQL tool over the *full* raw tables. The model writes DuckDB SQL to
answer any question down to the individual row, and the schema it sees is
generated from the data itself — so it scales as columns/rows change.
"""

from __future__ import annotations

import json
import re

import pandas as pd

from quality_dashboard.config import (
    DEFECT_FILE,
    EXTERNAL_FAILURE_FILE,
    NCR_CASES_FILE,
    SCRAP_FILE,
)
from quality_dashboard.data_loaders import (
    load_defect_data,
    load_external_failure_data,
    load_ncr_cases,
    load_scrap_data,
)


DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = "deepseek-chat"
MAX_RESULT_ROWS = 60       # rows returned to the model per query
MAX_TOOL_ITERATIONS = 6    # safety cap on the query/answer loop
MAX_HISTORY_TURNS = 12     # trailing user/assistant turns sent to the model


# Each table maps source column -> clean snake_case name the model writes SQL against.
# Only listed columns are exposed; unlisted/empty source columns are dropped.
_NCR_COLUMNS = {
    "Number": "number",
    "Subject": "subject",
    "Company": "company",
    "Profile": "profile",
    "Status": "status",
    "Stage": "stage",
    "Assigned To": "assigned_to",
    "Priority": "priority",
    "Origin": "origin",
    "Type": "type",
    "Item": "item",
    "Issue": "issue",
    "Incident Date": "incident_date",
    "Date Created": "date_created",
    "Date Closed": "date_closed",
    "Is Open": "is_open",
    "Is Closed": "is_closed",
    "Closure Days": "closure_days",
    "Age Days": "age_days",
}
_SCRAP_COLUMNS = {
    "Id": "id",
    "Document Number": "document_number",
    "Date": "date",
    "Item": "item",
    "Quantity": "quantity",
    "Into Quarantine": "into_quarantine",
    "Confirmed Scrap": "confirmed_scrap",
    "Quarantine Balance": "quarantine_balance",
    "Absolute Movement": "absolute_movement",
    "Type": "type",
    "User": "user",
    "Employee": "employee",
    "Location": "location",
    "Memo": "memo",
    "Customer": "customer",
}
_WEIGHT_COLUMNS = {
    "Date": "date",
    "Inspector": "inspector",
    "Assembly Item": "assembly_item",
    "Work Order": "work_order",
    "Expected Target": "expected_target",
    "Expected Low": "expected_low",
    "Expected High": "expected_high",
    "Tolerance Low": "tolerance_low",
    "Tolerance High": "tolerance_high",
    "Actual Weight": "actual_weight",
    "Variance": "variance",
    "Absolute Variance": "absolute_variance",
    "Variance Percent": "variance_percent",
    "Weight Status": "weight_status",
    "Measurement Slot": "measurement_slot",
}
_CLAIM_COLUMNS = {
    "UPC": "upc",
    "Item Description": "item_description",
    "Item Number": "item_number",
    "Claim Reason": "claim_reason",
    "Claim Amount": "claim_amount",
}
_DEPARTMENT_COLUMNS = {
    "Department Number": "department_number",
    "Department Description": "department_description",
    "Allowance Amount": "allowance_amount",
    "Claim Amount": "claim_amount",
}


def _select_rename(df: pd.DataFrame, mapping: dict[str, str]) -> pd.DataFrame:
    present = {src: dst for src, dst in mapping.items() if src in df.columns}
    return df[list(present)].rename(columns=present).copy()


def build_frames() -> dict[str, pd.DataFrame]:
    """Load every source file and return clean, query-ready tables keyed by table name."""
    ext = load_external_failure_data(EXTERNAL_FAILURE_FILE)
    return {
        "ncr_cases": _select_rename(load_ncr_cases(NCR_CASES_FILE), _NCR_COLUMNS),
        "scrap": _select_rename(load_scrap_data(SCRAP_FILE), _SCRAP_COLUMNS),
        "weight_inspection": _select_rename(load_defect_data(DEFECT_FILE), _WEIGHT_COLUMNS),
        "external_claims": _select_rename(ext.top_claims, _CLAIM_COLUMNS),
        "external_departments": _select_rename(ext.department_summary, _DEPARTMENT_COLUMNS),
    }


def describe_schema(frames: dict[str, pd.DataFrame]) -> str:
    """Auto-generate a schema doc: columns, types, date ranges, and low-cardinality value lists."""
    lines: list[str] = []
    for name, df in frames.items():
        lines.append(f"TABLE {name} ({len(df):,} rows):")
        for col in df.columns:
            dtype = df[col].dtype
            if pd.api.types.is_datetime64_any_dtype(dtype):
                mn, mx = df[col].min(), df[col].max()
                rng = f" range {mn:%Y-%m-%d} to {mx:%Y-%m-%d}" if pd.notna(mn) else ""
                lines.append(f"  - {col} (date){rng}")
            elif pd.api.types.is_bool_dtype(dtype):
                lines.append(f"  - {col} (true/false)")
            elif pd.api.types.is_numeric_dtype(dtype):
                lines.append(f"  - {col} (number)")
            else:
                distinct = df[col].dropna().astype(str)
                distinct = distinct[distinct.str.strip() != ""]
                n_unique = distinct.nunique()
                if n_unique <= 25:
                    values = ", ".join(sorted(distinct.unique())[:25])
                    lines.append(f"  - {col} (text) values: {values}")
                else:
                    lines.append(f"  - {col} (text, {n_unique:,} distinct values)")
        lines.append("")
    return "\n".join(lines).strip()


def describe_overview(frames: dict[str, pd.DataFrame]) -> str:
    """A handful of headline totals so trivial questions don't need a query."""
    ncr = frames["ncr_cases"]
    fpc_ncr = ncr[ncr["profile"] == "FPC | NCR"]
    complaints = fpc_ncr[fpc_ncr["assigned_to"] == "Sheri King"]
    scrap = frames["scrap"]
    weight = frames["weight_inspection"]
    claims = frames["external_claims"]
    depts = frames["external_departments"]
    return (
        f"- NCR cases (profile 'FPC | NCR'): {len(fpc_ncr):,}\n"
        f"- Customer complaints (FPC | NCR assigned to Sheri King): {len(complaints):,}\n"
        f"- Scrap transactions: {len(scrap):,} across {scrap['item'].nunique():,} items; "
        f"confirmed scrap {scrap['confirmed_scrap'].sum():,.0f} units\n"
        f"- Weight measurements: {len(weight):,} across {weight['assembly_item'].nunique():,} items\n"
        f"- External-failure claim lines: {len(claims):,}; "
        f"authoritative department claim total ${depts['claim_amount'].sum():,.0f}"
    )


_SYSTEM_TEMPLATE = """\
You are the quality analytics assistant for Fairfield Processing Corporation (FPC). You help \
quality and operations managers explore NCR cases, customer complaints, weight inspection, \
scrap/quarantine movement, and Walmart/Amazon external-failure claims. Today is {today}.

You have one tool, `run_sql`, that runs a read-only DuckDB SQL SELECT against the tables below \
and returns rows. Use it for ANY specific figure, filter, ranking, breakdown, single-record \
lookup, or trend — this is how you read the finest detail in the data. You may run several \
queries to build an answer. Never invent or estimate a number: if you state a figure, it must \
come from a query result (or the headline totals below).

TABLES AND COLUMNS (write SQL against these exact lowercase names):
{schema}

KEY DEFINITIONS AND GOTCHAS:
- NCR analysis means ncr_cases WHERE profile = 'FPC | NCR'. The same table also holds \
'FPC | Support' and 'FPC | Customer Support' rows — exclude those unless the user asks about them.
- Customer complaints = ncr_cases WHERE profile = 'FPC | NCR' AND assigned_to = 'Sheri King'.
- A case is OPEN when status = 'Escalated'; it is CLOSED when stage = 'Closed' and date_closed \
is not null. closure_days and age_days are already computed per row; use median for typical \
closure time (a few very slow cases skew the average).
- scrap: a positive quantity is units moved INTO quarantine; confirmed_scrap holds the units \
confirmed scrapped (already a positive number). Sum confirmed_scrap for scrap volume. There is \
no shipment/order denominator anywhere, so a true scrap or complaint RATE cannot be computed — \
say so if asked.
- external_departments.claim_amount is the authoritative reported claim total per department \
(the full number). external_claims is the itemized detail sheet and sums LOWER than the \
department total because not every claim is itemized. Use external_departments for company-wide \
totals and external_claims for item-level or reason-level detail.
- weight_inspection: variance = actual_weight - expected_target; weight_status classifies each \
measurement as within range / above / below.

HEADLINE TOTALS (for quick reference — query for anything more specific):
{overview}

STYLE: Lead with the answer. Write concise, readable prose — usually 2-5 sentences; expand only \
when asked. Light **bold** for key numbers is fine; avoid tables and headings in this small chat \
window. If a figure genuinely isn't in the data, say what you do have and what's missing. If \
someone asks something clearly unrelated to FPC quality data, politely decline and steer back."""


def build_system_prompt(frames: dict[str, pd.DataFrame]) -> str:
    return _SYSTEM_TEMPLATE.format(
        today=pd.Timestamp.today().strftime("%Y-%m-%d"),
        schema=describe_schema(frames),
        overview=describe_overview(frames),
    )


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "run_sql",
            "description": (
                "Run a single read-only DuckDB SQL SELECT against the FPC quality tables and "
                "get the resulting rows back as JSON. Use it for any specific number, filter, "
                "ranking, aggregate, record lookup, or trend. Table and column names are given "
                "in the system prompt."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "A single DuckDB SELECT statement (no semicolon needed).",
                    }
                },
                "required": ["query"],
            },
        },
    }
]


_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|attach|detach|copy|pragma|install|load|"
    r"export|import|call|merge|truncate|replace|vacuum|reindex|grant|revoke)\b",
    re.IGNORECASE,
)


def _is_safe_select(sql: str) -> tuple[bool, str]:
    statement = sql.strip().rstrip(";").strip()
    if not statement:
        return False, "Empty query."
    if ";" in statement:
        return False, "Only a single statement is allowed (no semicolons)."
    lowered = statement.lower()
    if not (lowered.startswith("select") or lowered.startswith("with")):
        return False, "Only SELECT queries are allowed."
    if _FORBIDDEN.search(statement):
        return False, "Only read-only SELECT queries are allowed."
    return True, ""


def run_sql(frames: dict[str, pd.DataFrame], query: str) -> str:
    """Execute a guarded SELECT against the frames; return a JSON string for the model."""
    import duckdb

    ok, reason = _is_safe_select(query)
    if not ok:
        return json.dumps({"error": reason})

    con = duckdb.connect()
    try:
        for name, df in frames.items():
            con.register(name, df)
        result = con.execute(query).fetchdf()
    except Exception as exc:  # surface the DB error so the model can fix its SQL
        return json.dumps({"error": f"{type(exc).__name__}: {exc}"})
    finally:
        con.close()

    total = len(result)
    shown = result.head(MAX_RESULT_ROWS)
    payload = {
        "row_count": int(total),
        "returned_rows": int(len(shown)),
        "truncated": bool(total > len(shown)),
        "rows": json.loads(shown.to_json(orient="records", date_format="iso")),
    }
    return json.dumps(payload, default=str)


def run_agent(
    frames: dict[str, pd.DataFrame],
    system_prompt: str,
    api_key: str,
    history: list[dict[str, str]],
) -> tuple[str, list[str]]:
    """Run the tool-calling loop. Returns (answer_text, list_of_sql_queries_run)."""
    if not api_key:
        return ("The assistant isn't configured (missing API key).", [])

    from openai import OpenAI

    client = OpenAI(api_key=api_key, base_url=DEEPSEEK_BASE_URL, timeout=60)
    messages: list[dict] = [{"role": "system", "content": system_prompt}]
    messages += history[-MAX_HISTORY_TURNS:]
    executed: list[str] = []

    try:
        for _ in range(MAX_TOOL_ITERATIONS):
            response = client.chat.completions.create(
                model=DEEPSEEK_MODEL,
                messages=messages,
                tools=TOOLS,
                temperature=0.1,
                max_tokens=1200,
            )
            message = response.choices[0].message

            if not message.tool_calls:
                return (message.content or "", executed)

            messages.append(
                {
                    "role": "assistant",
                    "content": message.content or "",
                    "tool_calls": [
                        {
                            "id": call.id,
                            "type": "function",
                            "function": {
                                "name": call.function.name,
                                "arguments": call.function.arguments,
                            },
                        }
                        for call in message.tool_calls
                    ],
                }
            )

            for call in message.tool_calls:
                if call.function.name == "run_sql":
                    try:
                        args = json.loads(call.function.arguments or "{}")
                    except json.JSONDecodeError:
                        args = {}
                    query = (args.get("query") or "").strip()
                    executed.append(query)
                    output = run_sql(frames, query)
                else:
                    output = json.dumps({"error": f"Unknown tool {call.function.name}"})
                messages.append(
                    {"role": "tool", "tool_call_id": call.id, "content": output}
                )

        return (
            "I ran several queries but couldn't fully resolve that. Try narrowing the question.",
            executed,
        )
    except Exception as exc:
        return (f"The assistant hit an error reaching the AI service ({type(exc).__name__}).", executed)
