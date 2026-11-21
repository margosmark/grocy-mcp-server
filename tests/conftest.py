"""Shared test setup: force hermetic env before server.py is imported."""

import os
import sys

# server.py reads these at import time — pin them so tests never touch a real instance
os.environ["GROCY_URL"] = "http://grocy.test"
os.environ["GROCY_KEY"] = "test-key-not-real"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
