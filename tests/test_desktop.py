"""Synthetic project transaction and input-boundary tests (no personal media)."""
import copy
import json
import multiprocessing
from pathlib import Path
import uuid

import pytest
from piano_fingering import desktop as d


def write(path, value):
    path.write_text(json.dumps(value))


@pytest.fixture
def project(tmp_path):
    root = tmp_path / 'Synthetic.fingeringproject'
    (root / 'Inputs').mkdir(parents=True); (root / 'Runs').mkdir()
    (root / 'Inputs/video.mp4').write_bytes(b'synthetic input')
    (root / 'Inputs/score.pdf').write_bytes(b'%PDF-1.4\nsynthetic')
    run_id = str(uuid.uuid4()); run = root / 'Runs' / run_id; run.mkdir()
    write(root / 'project.json', dict(schema=1, id=str(uuid.uuid4()), name='Synthetic',
          videoExtension='.mp4', status='ready', editRevision=0, edits={}, currentRun=run_id, activeJob=None))
    write(run / 'run.json', dict(schema=1, status='complete', overrides={}, revision=0))
    for name in d.OUTPUTS.values(): (run / name).write_bytes(b'synthetic output')
    write(run / 'automatic_predictions.json', {'predictions': [dict(event_id='ev_0000', midi_pitch=60,
          pitch_name='C4', measure=1, onset_sec=0.5, auto_hand='R', auto_finger='1', auto_confidence_tier='low')]})
    write(run / 'sanitized_summary.json', {})
    write(run / 'parsed_score.json', {'notes': []})
    record = json.loads((run / 'run.json').read_text())
    record['outputs'] = {name: d._digest(run / name) for name in d.OUTPUTS.values()}
    write(run / 'run.json', record)
    for name in ('transcribed_notes.json', 'alignment.json', 'hand_poses.json', 'keyboard_calibration.json', 'cache_manifest.json', 'predictions.json', 'overrides.json'):
        write(run / name, {})
    return root


def test_correction_is_pending_preserves_auto_and_fences_stale_writes(project):
    before = d.review_project(project)
    original = (project / 'Runs' / before['runID'] / 'automatic_predictions.json').read_bytes()
    after = d.set_correction(str(project), 'ev_0000', 'L', '3', before['runID'], 0)
    assert after['dirty'] and after['revision'] == 1
    assert after['notes'][0]['autoFinger'] == '1' and after['notes'][0]['finger'] == '3'
    assert (project / 'Runs' / before['runID'] / 'automatic_predictions.json').read_bytes() == original
    with pytest.raises(d.DesktopError, match='another window'):
        d.set_correction(str(project), 'ev_0000', 'R', '2', before['runID'], 0)
    with pytest.raises(d.DesktopError, match='Update the video'):
        d.export_project(str(project), str(project.parent), 'Export', ['notes'], str(uuid.uuid4()), before['runID'], 1)
    reset = d.set_correction(str(project), 'ev_0000', None, None, before['runID'], 1)
    assert not reset['dirty'] and reset['notes'][0]['finger'] == '1'


def test_export_is_exclusive_and_keeps_job_lease(project):
    destination = project.parent / 'Export'; destination.mkdir()
    (destination / 'keep.txt').write_text('keep')
    with pytest.raises(d.DesktopError, match='already exists'):
        d.export_project(str(project), str(project.parent), 'Export', ['notes'], str(uuid.uuid4()), d.review_project(project)['runID'], 0)
    assert (destination / 'keep.txt').read_text() == 'keep'
    job = str(uuid.uuid4())
    result = d.export_project(str(project), str(project.parent), 'Fresh export', ['notes'], job, d.review_project(project)['runID'], 0)
    assert [p.name for p in Path(result['exported']).iterdir()] == ['predictions.csv']
    assert d.review_project(project)['busy']
    with pytest.raises(d.DesktopError, match='different job'):
        d.finalize_job(str(project), str(uuid.uuid4()), 'success')
    assert not d.finalize_job(str(project), job, 'success')['busy']


def test_exclusive_rename_never_replaces_even_empty_directory(tmp_path):
    source = tmp_path / 'source'; source.mkdir(); (source / 'keep').write_text('new')
    target = tmp_path / 'target'; target.mkdir()
    with pytest.raises(d.DesktopError): d._exclusive_rename(source, target)
    assert list(target.iterdir()) == [] and (source / 'keep').exists()


def test_lease_blocks_edits_and_recovery_retains_original(project):
    m = json.loads((project / 'project.json').read_text())
    m['activeJob'] = dict(id=str(uuid.uuid4()), operation='analyze'); write(project / 'project.json', m)
    before = (project / 'project.json').read_bytes()
    with pytest.raises(d.DesktopError, match='not been finalized'):
        d.set_correction(str(project), 'ev_0000', 'R', '2', m['currentRun'], 0)
    recovered = d.recover_project(str(project), str(project.parent), 'Recovered')
    assert not d.review_project(recovered)['busy']
    assert d.review_project(recovered)['name'] == 'Recovered'
    assert (project / 'project.json').read_bytes() == before
    assert d.review_project(recovered)['notes'][0]['autoFinger'] == '1'


def hold_lock(root, ready, release):
    with d._lock(Path(root)):
        ready.set(); release.wait(10)


def test_other_process_lock_blocks_mutations_and_recovery(project):
    ctx = multiprocessing.get_context('spawn'); ready, release = ctx.Event(), ctx.Event()
    process = ctx.Process(target=hold_lock, args=(str(project), ready, release)); process.start()
    try:
        assert ready.wait(10)
        with pytest.raises(d.DesktopError, match='Another'):
            d.recover_project(str(project), str(project.parent), 'Blocked')
    finally:
        release.set(); process.join(10)
    assert process.exitcode == 0


@pytest.mark.parametrize('mutation', ['symlink', 'traversal', 'huge', 'duplicate', 'nan', 'bad_note', 'bad_revision'])
def test_project_boundaries_reject_untrusted_records(project, mutation):
    m = json.loads((project / 'project.json').read_text()); run = project / 'Runs' / m['currentRun']
    if mutation == 'symlink':
        (run / 'predictions.csv').unlink(); (run / 'predictions.csv').symlink_to('/etc/hosts')
    elif mutation == 'traversal': m['currentRun'] = '../outside'; write(project / 'project.json', m)
    elif mutation == 'huge': (project / 'project.json').write_bytes(b' ' * (d.MAX_JSON + 1))
    elif mutation == 'duplicate': (project / 'project.json').write_text('{"schema":1,"schema":1}')
    elif mutation == 'nan': (project / 'project.json').write_text('{"schema":NaN}')
    elif mutation == 'bad_revision': m['editRevision'] = True; write(project / 'project.json', m)
    else:
        value = json.loads((run / 'automatic_predictions.json').read_text())
        value['predictions'][0]['onset_sec'] = float('inf'); write(run / 'automatic_predictions.json', value)
    with pytest.raises(d.DesktopError): d.review_project(project)


def test_publication_fence_detects_changed_revision(project):
    _, original = d.open_project(project)
    altered = copy.deepcopy(original); altered['editRevision'] += 1; write(project / 'project.json', altered)
    with pytest.raises(d.DesktopError, match='changed while processing'): d._check_revision(project, original)


def test_changed_nonempty_output_is_rejected(project):
    _, m = d.open_project(project)
    (project / 'Runs' / m['currentRun'] / 'teaching_video.mp4').write_bytes(b'corrupt nonempty')
    with pytest.raises(d.DesktopError, match='damaged'): d.review_project(project)


def test_stale_export_is_rejected_before_lease_or_copy(project):
    _, m = d.open_project(project)
    with pytest.raises(d.DesktopError, match='another window'):
        d.export_project(str(project), str(project.parent), 'Unseen', ['notes'], str(uuid.uuid4()), m['currentRun'], 10)
    assert not (project.parent / 'Unseen').exists() and not d.review_project(project)['busy']


@pytest.mark.parametrize('render_only', [False, True])
def test_failed_attempt_preserves_previous_result_and_corrections(project, monkeypatch, render_only):
    from piano_fingering import cli
    before = d.review_project(project)
    edited = d.set_correction(str(project), 'ev_0000', 'L', '3', before['runID'], 0)
    monkeypatch.setattr(d, 'inspect_inputs', lambda *a: {})
    monkeypatch.setattr(d, '_validate_cache', lambda *a: None)
    def failed(*a, **kw): raise RuntimeError('synthetic failure')
    monkeypatch.setattr(cli, 'run_pipeline', failed)
    job = str(uuid.uuid4())
    with pytest.raises(RuntimeError, match='synthetic'):
        d.process_project(str(project), job, render_only, None, before['runID'], 1)
    current = d.review_project(project)
    assert current['runID'] == before['runID'] and current['busy'] and current['dirty']
    assert current['notes'][0]['finger'] == '3'
    finalized = d.finalize_job(str(project), job, 'failed')
    assert not finalized['busy'] and finalized['dirty'] and finalized['runID'] == before['runID']


def test_untrusted_cache_size_and_shape_are_rejected(tmp_path):
    from piano_fingering.cli import CACHED_STAGE_FILES
    for name in (*CACHED_STAGE_FILES, 'cache_manifest.json'): write(tmp_path / name, {})
    with pytest.raises(d.DesktopError): d._validate_cache(tmp_path)
    (tmp_path / 'transcribed_notes.json').write_bytes(b' ' * (d.MAX_JSON + 1))
    with pytest.raises(d.DesktopError): d._validate_cache(tmp_path)


def valid_cache(tmp_path):
    from piano_fingering.models import PerfNote, ScoreNote, ScoreMeasure, FramePose, FrameCalibration, MeasureTiming
    write(tmp_path / 'transcribed_notes.json', {'metadata': {}, 'notes': [PerfNote('p0', .1, .4, 60, 80).to_dict()]})
    measure = ScoreMeasure(1, 0, 0, 20, 20, 500, 300, 30, 66, 200, 236, 9, 4, 4)
    note = ScoreNote('s0', 0, 0, 1, 0, 1, 'treble', 1, 60, 'C4', 50, 50, (45, 45, 55, 55), 'chord0')
    write(tmp_path / 'parsed_score.json', {'metadata': {}, 'measures': [measure.to_dict()], 'notes': [note.to_dict()]})
    write(tmp_path / 'hand_poses.json', {'metadata': {}, 'frames': [FramePose(0, 0, 64, 48, []).to_dict()]})
    calibration = FrameCalibration(0, 0, [[1, 0, 0], [0, 1, 0], [0, 0, 1]], None, 0, 0, False)
    write(tmp_path / 'keyboard_calibration.json', {'metadata': {}, 'frames': [calibration.to_dict()]})
    write(tmp_path / 'alignment.json', {'metadata': {}, 'pairs': [dict(perf_event_id='p0', score_note_id='s0', alignment_status='matched', expected_time_sec=.1, timing_residual_sec=0)], 'measure_timings': [MeasureTiming(1, 0, 0, 0, 1, 1).to_dict()]})
    write(tmp_path / 'cache_manifest.json', {})


@pytest.mark.parametrize('damage', ['matrix', 'nan', 'frame_identity'])
def test_valid_cache_passes_then_corruption_is_rejected(tmp_path, damage):
    valid_cache(tmp_path)
    d._validate_cache(tmp_path)
    path = tmp_path / 'keyboard_calibration.json'; value = json.loads(path.read_text())
    if damage == 'matrix': value['frames'][0]['h_white'] = [[1, 2]]
    elif damage == 'nan': value['frames'][0]['residual_kw'] = float('nan')
    else: value['frames'][0]['frame_index'] = 12
    write(path, value)
    with pytest.raises(d.DesktopError): d._validate_cache(tmp_path)


def test_render_checks_oversized_cache_before_copying(project, monkeypatch):
    _, m = d.open_project(project); previous = project / 'Runs' / m['currentRun']
    (previous / 'hand_poses.json').write_bytes(b' ' * (d.MAX_JSON + 1))
    monkeypatch.setattr(d, 'inspect_inputs', lambda *a: {})
    copied = []
    def forbidden_copy(*a): copied.append(a); raise AssertionError('Should validate before copying')
    monkeypatch.setattr(d, '_copy_file', forbidden_copy)
    with pytest.raises(d.DesktopError):
        d.process_project(str(project), str(uuid.uuid4()), True, None, m['currentRun'], 0)
    assert copied == []
