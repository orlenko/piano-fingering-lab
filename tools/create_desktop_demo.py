"""Create synthetic media and a review fixture; never a model-accuracy example."""
from fractions import Fraction
import json
from pathlib import Path
import sys
import uuid

import av
import numpy as np
from PIL import Image, ImageDraw
from reportlab.pdfgen import canvas
from piano_fingering.desktop import _atomic, _digest, OUTPUTS


def main():
    parent = Path(sys.argv[1] if len(sys.argv) > 1 else '.local/desktop-demo')
    root = parent / 'A little C major.fingeringproject'
    if root.exists(): raise SystemExit('Choose a new output folder.')
    (root / 'Inputs').mkdir(parents=True); run_id = str(uuid.uuid4())
    run = root / 'Runs' / run_id; run.mkdir(parents=True)
    pdf = root / 'Inputs/score.pdf'
    c = canvas.Canvas(str(pdf), pagesize=(595, 842)); c.setTitle('Synthetic practice scale')
    c.setFont('Helvetica', 22); c.drawString(60, 760, 'A little C major')
    c.setFont('Helvetica', 10); c.drawString(60, 735, 'Synthetic interface fixture. Not an inference or accuracy demonstration.')
    for y in (650, 520):
        for k in range(5): c.line(65, y - 9 * k, 530, y - 9 * k)
        for k in range(8): c.ellipse(90 + 50 * k, y - 32 + k * 4, 100 + 50 * k, y - 26 + k * 4, fill=1)
    c.save()
    import shutil
    shutil.copyfile(pdf, run / OUTPUTS['score'])
    mp4 = run / OUTPUTS['video']
    with av.open(str(mp4), 'w') as container:
        stream = container.add_stream('libx264', rate=30); stream.width = 960; stream.height = 540; stream.pix_fmt = 'yuv420p'
        for i in range(90):
            image = Image.new('RGB', (960, 540), '#f3f1e8'); draw = ImageDraw.Draw(image)
            draw.text((36, 25), 'SYNTHETIC PRACTICE SESSION', fill='#344539', font_size=22)
            draw.text((36, 65), 'Interface preview only — not model output', fill='#777777', font_size=16)
            for k in range(14):
                x = 34 + k * 64
                draw.rectangle((x, 180, x + 62, 440), fill='white', outline='#344539', width=2)
                if k % 7 in (0, 1, 3, 4, 5): draw.rectangle((x + 44, 180, x + 78, 335), fill='#28372f')
            active = (i // 12) % 8
            draw.rounded_rectangle((40 + active * 64, 350, 93 + active * 64, 430), radius=8, fill='#a6c9af')
            draw.text((36, 485), 'Likely  /  Uncertain  /  Unknown  /  Your correction', fill='#344539', font_size=18)
            frame = av.VideoFrame.from_ndarray(np.asarray(image), format='rgb24')
            frame.pts = i; frame.time_base = Fraction(1, 30)
            for packet in stream.encode(frame): container.mux(packet)
        for packet in stream.encode(None): container.mux(packet)
    shutil.copyfile(mp4, root / 'Inputs/video.mp4')
    image.save(run / OUTPUTS['excerpt'])
    (run / OUTPUTS['notes']).write_text('event_id,pitch,final_finger\nev_0000,C4,1\n')
    notes, score_notes = [], []
    for i, pitch in enumerate(['C4', 'D4', 'E4', 'F4', 'G4', 'A4', 'B4', 'C5']):
        notes.append(dict(event_id=f'ev_{i:04d}', score_note_id=f'synthetic_{i}', onset_sec=i * .3,
             midi_pitch=[60, 62, 64, 65, 67, 69, 71, 72][i], pitch_name=pitch, measure=1 + i // 4,
             auto_hand='unknown' if i == 3 else 'R', auto_finger='unknown' if i == 3 else str(i % 5 + 1),
             auto_confidence_tier='unknown' if i == 3 else ('low' if i in (2, 5) else 'high'),
             abstain_reason='no_frames_in_attack_window' if i == 3 else None))
        score_notes.append(dict(score_note_id=f'synthetic_{i}', page_index=0, x_pt=95 + 50 * i, y_pt=842 - (623 + i * 4)))
    _atomic(run / 'automatic_predictions.json', {'predictions': notes})
    _atomic(run / 'parsed_score.json', {'notes': score_notes})
    _atomic(run / 'sanitized_summary.json', {'synthetic_fixture': True})
    for name in ('transcribed_notes.json', 'alignment.json', 'hand_poses.json', 'keyboard_calibration.json', 'cache_manifest.json', 'predictions.json', 'overrides.json'): _atomic(run / name, {})
    _atomic(run / 'run.json', dict(schema=1, status='complete', overrides={}, revision=0, outputs={n: _digest(run / n) for n in OUTPUTS.values()}))
    _atomic(root / 'project.json', dict(schema=1, syntheticFixture=True, id=str(uuid.uuid4()), name='A little C major', videoExtension='.mp4',
        currentRun=run_id, editRevision=0, edits={}, activeJob=None, status='ready'))
    print('Created synthetic review fixture. It is not suitable for inference validation.')

if __name__ == '__main__': main()
