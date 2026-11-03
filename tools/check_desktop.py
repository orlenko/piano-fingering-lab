"""Private, opt-in end-to-end check using operator-approved local inputs.

Run: .venv/bin/python tools/check_desktop.py --inputs .local/inputs.json
No media, paths, logs or per-note labels are printed. Work stays in .local/.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--inputs', type=Path, required=True)
    args = parser.parse_args()
    work = ROOT / '.local/desktop-check' / str(uuid.uuid4()); work.mkdir(parents=True)
    relocation = Path(tempfile.mkdtemp(prefix='fingering-studio-relocation-'))
    app = relocation / 'A folder with spaces' / 'Fingering Studio.app'
    print('Copying app outside the checkout…', flush=True)
    shutil.copytree(ROOT / '.local/dist/Fingering Studio.app', app, symlinks=True)
    resources = app / 'Contents/Resources'
    counter = 0
    def call(operation, values=(), cancel=None, expect_error=False):
        nonlocal counter
        counter += 1; job = work / f'job-{counter:02d}'; job.mkdir()
        environment = {'PATH': '/usr/bin:/bin'}
        if cancel is not None: environment['STUDIO_TEST_CANCEL_AFTER'] = str(cancel)
        command = [str(ROOT / '.local/worker-harness'), str(resources), str(job), operation, *map(str, values)]
        with (job / 'protocol.jsonl').open('w') as log:
            process = subprocess.Popen(command, cwd=relocation, env=environment, text=True, stdout=subprocess.PIPE, stderr=log)
            final = None
            for line in process.stdout:
                log.write(line); log.flush()
                value = json.loads(line)
                if value.get('type') == 'progress': print(f"Stage {value['stage']}/7: {value['label']}", flush=True)
                else: final = value
            assert process.wait(timeout=1830) == 0 and final and final['cleanupConfirmed'], 'Owned-child cleanup failed'
        if cancel is not None:
            assert final['cancelled']; return final
        errors = [m for m in final['messages'] if m['type'] == 'error']
        if expect_error:
            assert errors and final['exitCode'] != 0; return errors[-1]
        assert not errors, errors[-1]['message'] if errors else 'Unexpected worker failure'
        assert final['exitCode'] == 0
        return [m['data'] for m in final['messages'] if m['type'] == 'result'][-1]
    try:
        health = call('health')
        assert health['ready'] and health['helperPresent'] and Path(health['packageOrigin']).is_relative_to(resources.resolve())
        print('PASS relocated offline runtime, model, and native helper', flush=True)
        raw = json.loads(args.inputs.read_text())
        video = raw.get('video') or raw.get('video_path') or raw['performance_video']
        score = raw.get('score') or raw.get('score_path') or raw['score_pdf_path']
        created = call('create', ['--video', video, '--score', score, '--destination', work, '--name', 'Local validation'])
        project = created['project']; job = str(uuid.uuid4())
        call('analyze', ['--project', project, '--job-id', job, '--expected-run', 'none', '--expected-revision', '0'])
        reviewed = call('finalize', ['--project', project, '--job-id', job, '--outcome', 'success'])
        assert reviewed['hasResults'] and not reviewed['busy'] and len(reviewed['notes']) > 0
        first_run, first_revision = reviewed['runID'], reviewed['revision']
        automatic = Path(project) / 'Runs' / first_run / 'automatic_predictions.json'
        original = hashlib.sha256(automatic.read_bytes()).hexdigest()
        note = next(n for n in reviewed['notes'] if n['autoHand'] in ('L', 'R'))
        corrected = call('correct', ['--project', project, '--event', note['id'], '--expected-run', first_run,
                         '--expected-revision', first_revision, '--hand', 'L', '--finger', '5'])
        assert corrected['dirty'] and corrected['revision'] == first_revision + 1
        refused = call('export', ['--project', project, '--destination', work, '--name', 'Should not exist',
                         '--job-id', str(uuid.uuid4()), '--expected-run', first_run, '--expected-revision', corrected['revision'], '--kinds', 'video'], expect_error=True)
        assert refused['code'] == 'render_needed'
        job = str(uuid.uuid4())
        call('render', ['--project', project, '--job-id', job, '--expected-run', first_run, '--expected-revision', corrected['revision']])
        updated = call('finalize', ['--project', project, '--job-id', job, '--outcome', 'success'])
        assert not updated['dirty'] and updated['runID'] != first_run
        assert hashlib.sha256(automatic.read_bytes()).hexdigest() == original
        assert next(n for n in updated['notes'] if n['id'] == note['id'])['corrected']
        print('PASS full analysis, reopen, correction provenance, cached update, and old-result preservation', flush=True)
        job = str(uuid.uuid4())
        exported = call('export', ['--project', project, '--destination', work, '--name', 'Validation export', '--job-id', job,
                         '--expected-run', updated['runID'], '--expected-revision', updated['revision'], '--kinds', 'video', 'score', 'excerpt', 'notes'])
        call('finalize', ['--project', project, '--job-id', job, '--outcome', 'success'])
        assert len(list(Path(exported['exported']).iterdir())) == 4
        job = str(uuid.uuid4())
        call('analyze', ['--project', project, '--job-id', job, '--expected-run', updated['runID'], '--expected-revision', updated['revision']], cancel=4)
        stopped = call('finalize', ['--project', project, '--job-id', job, '--outcome', 'cancelled'])
        assert stopped['runID'] == updated['runID'] and not stopped['busy']
        print('PASS atomic four-file export and real-worker stop with previous result preserved', flush=True)
        import av
        with av.open(updated['video']) as container:
            stream = container.streams.video[0]
            times = [float(f.pts * f.time_base) for f in container.decode(stream)]
        assert len(times) <= 1000 and all(b > a for a, b in zip(times, times[1:]))
        with av.open(video) as container: source_count = sum(1 for _ in container.decode(video=0))
        assert len(times) == source_count
        summary = {'passed': True, 'sourceFrames': source_count, 'outputFrames': len(times),
                   'notes': len(reviewed['notes']), 'manualEditsInValidationOnly': 1,
                   'relocated': True, 'codeSigned': 'ad-hoc', 'musicianCorrectness': 'not measured'}
        (work / 'check-summary.json').write_text(json.dumps(summary, indent=2))
        print(json.dumps(summary), flush=True)
    finally:
        shutil.rmtree(relocation)

if __name__ == '__main__': main()
