"""Make the flat server modules importable when running pytest from server/."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
