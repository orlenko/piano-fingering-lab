"""Repeat native app launches with synthetic projects only; detect UI crashes."""
import json
from pathlib import Path
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
project = Path(sys.argv[1] if len(sys.argv) > 1 else '.local/desktop-demo/A little C major.fingeringproject').resolve()
assert json.loads((project / 'project.json').read_text()).get('syntheticFixture') is True, 'Use the generated synthetic fixture only'
work = ROOT / '.local/ui-check' / str(uuid.uuid4()); work.mkdir(parents=True)
app = ROOT / '.local/dist/Fingering Studio.app/Contents/MacOS/Fingering Studio'
for state in ('inputs', 'video', 'score', 'unknown'):
    report = work / (state + '.json')
    args = [str(app), '--ui-check', str(report), '--ui-state', state, '--snapshot', str(work / (state + '.png'))]
    if state != 'inputs': args += ['--project', str(project)]
    with (work / (state + '.log')).open('w') as log:
        child = subprocess.run(args, stdout=log, stderr=log, timeout=40)
    assert child.returncode == 0 and report.exists(), 'App launch failed for ' + state
    value = json.loads(report.read_text())
    assert value['ready'] and not value['busy'] and value['error'] is None, state
    if state != 'inputs':
        assert value['hasResults'] and value['notes'] == 8 and value['videoReady'] and value['scoreReady'], state
    if state == 'unknown': assert value['unknownIsUnset']
    print('PASS native launch / render / normal quit: ' + state, flush=True)
print('All four UI launch checks passed.', flush=True)
