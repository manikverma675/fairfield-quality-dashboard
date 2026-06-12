from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"

NCR_CASES_FILE = DATA_DIR / "NCR Cases.xls"
EXTERNAL_FAILURE_FILE = DATA_DIR / "External Failure cost Amazon.xlsx"
SCRAP_FILE = DATA_DIR / "Scrape Rate.csv"
DEFECT_FILE = DATA_DIR / "Defect Rate.xlsx"

# Statuses that mean a case is still actively open
OPEN_STATUSES = {"Escalated"}
CLOSED_STAGE = "Closed"

