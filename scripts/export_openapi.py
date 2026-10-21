"""Export the API contract without reading dotenv or connecting to services.

Run from the repository root:
apps/api/.venv/bin/python scripts/export_openapi.py
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api/src"))

from sinegor.core.config import Settings
from sinegor.main import create_app

settings = Settings(
    _env_file=None,
    app_env="test",
    database_url="postgresql+psycopg://contract:contract@localhost/contract_test",
)
contract = create_app(settings).openapi()
(ROOT / "contracts/openapi/api.json").write_text(
    json.dumps(contract, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
)
