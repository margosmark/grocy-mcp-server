import os
import sys
from pathlib import Path

# The server reads its config at import time, so set it before importing.
os.environ.setdefault("GROCY_URL", "https://grocy.test")
os.environ.setdefault("GROCY_KEY", "test-key")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
