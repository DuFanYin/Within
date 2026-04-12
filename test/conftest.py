"""
Ensure the repo root is on sys.path so `import app` works from the test dir.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
