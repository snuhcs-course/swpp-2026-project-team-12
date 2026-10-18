import sys
from pathlib import Path


TESTBED_ROOT = Path(__file__).resolve().parents[1]
if str(TESTBED_ROOT) not in sys.path:
    sys.path.insert(0, str(TESTBED_ROOT))
