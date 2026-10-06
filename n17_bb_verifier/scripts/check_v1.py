"""Compare all v1 fixture receipts with a pre-change binary, except seconds."""
import argparse
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('baseline', type=Path)
args = parser.parse_args()
results = {}
for directory in sorted((ROOT / 'tests/fixtures').iterdir()):
    if not directory.is_dir() or directory.name.startswith('v3-'):
        continue
    receipts = []
    for executable in [args.baseline.resolve(), ROOT / 'target/release/n17bb-verify']:
        run = subprocess.run([str(executable), str(directory), '--threads', '2'], capture_output=True, text=True)
        receipt = json.loads(run.stdout)
        assert run.returncode == (0 if receipt['status'] == 'PASS' else 1)
        receipt.pop('seconds')
        receipts.append(receipt)
    assert receipts[0] == receipts[1], directory
    results[directory.name] = dict(receipt_agreement=True, status=receipts[0]['status'])
output = ROOT / 'results/tighten/v1-agreement.json'
output.parent.mkdir(exist_ok=True)
output.write_text(json.dumps(results, indent=2) + '\n')
print(f'{len(results)} complete v1 receipts agree, excluding seconds.')
