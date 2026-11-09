from pathlib import Path
import json,hashlib
ROOT=Path(__file__).resolve().parent
def verify_code():
 for name,expected in json.loads((ROOT/'portable_code_lock.json').read_text()).items():
  assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==expected,name
 return True
