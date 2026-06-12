from __future__ import annotations

from pathlib import Path

import requests
import streamlit as st

from quality_dashboard.config import DATA_DIR, DEFECT_FILE, EXTERNAL_FAILURE_FILE, NCR_CASES_FILE, SCRAP_FILE

_FILES = {
    "NCR Cases.xls": NCR_CASES_FILE,
    "Defect Rate.xlsx": DEFECT_FILE,
    "transaction-history (2).csv": SCRAP_FILE,
    "External Failure cost Amazon.xlsx": EXTERNAL_FAILURE_FILE,
}


def ensure_data_files() -> None:
    """Download data files from the private GitHub repo if not present locally.

    Uses st.secrets["data_repo"] with keys: token, owner, repo, branch (optional).
    No-ops when all files already exist on disk (local development).
    """
    if all(p.exists() for p in _FILES.values()):
        return

    try:
        cfg = st.secrets["data_repo"]
        token: str = cfg["token"]
        owner: str = cfg["owner"]
        repo: str = cfg["repo"]
        branch: str = cfg.get("branch", "main")
    except (KeyError, AttributeError):
        return  # secrets not configured — pages will show their own missing-file error

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    headers = {"Authorization": f"token {token}"}

    for filename, dest in _FILES.items():
        if dest.exists():
            continue
        url = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{filename}"
        response = requests.get(url, headers=headers, timeout=60)
        response.raise_for_status()
        dest.write_bytes(response.content)
