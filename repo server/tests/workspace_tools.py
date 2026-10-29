"""Import workspace setup tools from their server-local location."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'shadow server/backend/setup'))

import configure_env
import workspace_services
