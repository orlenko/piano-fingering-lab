#!/usr/bin/env python3
"""Build an offline Apple Silicon internal alpha from the locked uv environment.

Run with the project Python 3.11. Outputs and third-party binaries stay in .local.
No downloading, source media, certificates, accounts, or hosted services involved.
"""
from __future__ import annotations
import argparse
import ast
import hashlib
import importlib.metadata as metadata
import json
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]

def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''): h.update(block)
    return h.hexdigest()

def call(*args):
    subprocess.run([str(a) for a in args], check=True)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--reuse-runtime', action='store_true', help='Local development only; refreshes first-party code and identity.')
    args = parser.parse_args()
    if sys.version_info[:2] != (3, 11) or sys.platform != 'darwin':
        raise SystemExit('Use .venv/bin/python on the Apple Silicon build Mac.')
    app = ROOT / '.local/dist/Fingering Studio.app'
    resources = app / 'Contents/Resources'
    runtime = resources / 'runtime'
    if runtime.exists() and not args.reuse_runtime:
        shutil.rmtree(app)
    resources.mkdir(parents=True, exist_ok=True)
    (app / 'Contents/MacOS').mkdir(exist_ok=True)
    (resources / 'native').mkdir(exist_ok=True)
    packages = runtime / 'lib/python3.11/site-packages'
    if not runtime.exists():
        base = Path(sys.base_prefix)
        if 'cpython-3.11' not in base.name:
            raise SystemExit('Expected the isolated uv Python build described in docs/desktop-plan.md.')
        print('Copying standalone Python and installed locked dependencies…', flush=True)
        shutil.copytree(base, runtime, symlinks=True, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        source = ROOT / '.venv/lib/python3.11/site-packages'
        shutil.copytree(source, packages, dirs_exist_ok=True, symlinks=True,
                        ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '*.pth', '__editable__*', 'direct_url.json'))
        for path in runtime.rglob('*'):
            if path.is_symlink():
                resolved = path.resolve()
                if not resolved.is_relative_to(runtime.resolve()):
                    raise SystemExit('Runtime has an external symlink: ' + str(path.relative_to(runtime)))
        # Build environment editable-install metadata is not a dependency or a runtime path.
        for path in packages.glob('piano_fingering_lab-*.dist-info'): shutil.rmtree(path)
    target = packages / 'piano_fingering'
    if target.exists(): shutil.rmtree(target)
    shutil.copytree(ROOT / 'src/piano_fingering', target, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    (resources / 'worker.py').write_text('from piano_fingering.desktop import main\nraise SystemExit(main())\n')
    tree = ast.parse((ROOT / 'src/piano_fingering/hand_pose.py').read_text())
    source = next(ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign)
                  and any(isinstance(t, ast.Name) and t.id == 'SWIFT_VISION_EXTRACTOR_SRC' for t in n.targets))
    swift = ROOT / '.local/build/HandPose.swift'
    swift.parent.mkdir(parents=True, exist_ok=True); swift.write_text(source)
    helper = resources / 'native/hand-pose'
    call('swiftc', '-O', '-target', 'arm64-apple-macos14.0', swift, '-o', helper)
    call('swiftc', '-O', '-swift-version', '5', '-target', 'arm64-apple-macos14.0', '-framework', 'AVKit',
         *sorted((ROOT / 'desktop/Sources').glob('*.swift')), '-o', app / 'Contents/MacOS/Fingering Studio')
    distributions = sorted([{'name': d.metadata['Name'], 'version': d.version}
                            for d in metadata.distributions(path=[str(packages)])], key=lambda d: d['name'].lower())
    identity = {'format': 1, 'platform': 'arm64-macos14', 'python': sys.version.split()[0],
                'lockSHA256': digest(ROOT / 'uv.lock'), 'distributions': distributions,
                'source': {p.name: digest(p) for p in sorted(target.glob('*.py'))},
                'handPoseSourceSHA256': hashlib.sha256(source.encode()).hexdigest(),
                'modelSHA256': digest(packages / 'transkun/pretrained/2.0.pt')}
    (target / 'runtime_identity.json').write_text(json.dumps(identity, indent=2) + '\n')
    (resources / 'RUNTIME-MANIFEST.json').write_text(json.dumps(identity, indent=2) + '\n')
    (resources / 'LICENSE.txt').write_text((ROOT / 'LICENSE').read_text())
    (resources / 'THIRD-PARTY-NOTICES.txt').write_text('''Fingering Studio — internal evaluation build

This bundle includes CPython and packages listed in RUNTIME-MANIFEST.json.
Their license, NOTICE and third-party files are retained inside runtime/.
The project MIT license does not license those components or musical works.

The bundled imageio-ffmpeg executable reports GPL version 2 or later, including
GPL-enabled codecs. The Python wrapper's BSD license does not cover that binary.
Before PUBLIC REDISTRIBUTION, establish corresponding-source compliance for
that exact binary and all included libraries, model redistribution terms, and
Developer ID signing/notarization. This local alpha is not a cleared release.
Transkun includes a pretrained model; its upstream MIT package notice is retained.
No user media or developer credentials are included. No hosted inference is used.
''')
    info = {'CFBundleExecutable': 'Fingering Studio', 'CFBundleName': 'Fingering Studio',
            'CFBundleDisplayName': 'Fingering Studio', 'CFBundleIdentifier': 'org.pianofingeringlab.studio',
            'CFBundleVersion': '1', 'CFBundleShortVersionString': '0.1.0', 'CFBundlePackageType': 'APPL',
            'LSMinimumSystemVersion': '14.0', 'NSHighResolutionCapable': True,
            'NSHumanReadableCopyright': 'Piano Fingering Lab contributors. Experimental internal alpha.',
            'UTExportedTypeDeclarations': [{'UTTypeIdentifier': 'org.pianofingeringlab.project',
                'UTTypeDescription': 'Fingering Studio project', 'UTTypeConformsTo': ['com.apple.package'],
                'UTTypeTagSpecification': {'public.filename-extension': ['fingeringproject']}}],
            'CFBundleDocumentTypes': [{'CFBundleTypeName': 'Fingering Studio project',
                'LSItemContentTypes': ['org.pianofingeringlab.project'], 'CFBundleTypeRole': 'Editor',
                'LSHandlerRank': 'Owner', 'LSTypeIsPackage': True}]}
    with (app / 'Contents/Info.plist').open('wb') as f: plistlib.dump(info, f)
    # Sign from the inside out. No Developer ID identity or credentials are used.
    print('Applying local ad-hoc signatures…', flush=True)
    magics = {b'\xcf\xfa\xed\xfe', b'\xfe\xed\xfa\xcf', b'\xca\xfe\xba\xbe', b'\xbe\xba\xfe\xca'}
    for path in runtime.rglob('*'):
        if path.is_file() and not path.is_symlink():
            with path.open('rb') as f: magic = f.read(4)
            if magic in magics: call('codesign', '--force', '--sign', '-', path)
    call('codesign', '--force', '--sign', '-', helper)
    call('codesign', '--force', '--sign', '-', app)
    call('codesign', '--verify', '--deep', '--strict', app)
    print('Built .local/dist/Fingering Studio.app', flush=True)

if __name__ == '__main__': main()
