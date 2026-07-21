# PyInstaller spec for HIFI Detector Python server
# Build: pyinstaller hifi-detector.spec
#
# This creates a standalone executable that runs the web server:
#   ./dist/hifi-detector web --port 8099

import os
import sys
from pathlib import Path

# Add hifi-detector root to path so we can import hifi_detector
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

block_cipher = None

a = Analysis(
    ['hifi_detector/cli.py'],
    pathex=[str(project_root)],
    binaries=[],
    datas=[
        # Bundle the web static files
        (str(project_root / 'hifi_detector' / 'web' / 'static'), 'hifi_detector/web/static'),
    ],
    hiddenimports=[
        'numpy',
        'scipy',
        'scipy.signal',
        'scipy.signal._spectral',
        'scipy.signal._savitzky_golay',
        'soundfile',
        'librosa',
        'typer',
        'rich',
        'pyloudnorm',
        'fastapi',
        'uvicorn',
        'uvicorn.loops',
        'uvicorn.loops.auto',
        'uvicorn.protocols',
        'uvicorn.protocols.http',
        'uvicorn.protocols.http.auto',
        'uvicorn.protocols.websockets',
        'uvicorn.protocols.websockets.auto',
        'uvicorn.lifespan',
        'uvicorn.lifespan.on',
        'starlette',
        'pydantic',
        'hifi_detector',
        'hifi_detector.core',
        'hifi_detector.core.audio_io',
        'hifi_detector.core.metadata',
        'hifi_detector.core.quality',
        'hifi_detector.core.loudness',
        'hifi_detector.core.dynamic_range',
        'hifi_detector.core.authenticity',
        'hifi_detector.web',
        'hifi_detector.web.server',
        'hifi_detector.web.routes',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# Collect resources from site-packages if any needed
# soundfile needs libsndfile
try:
    import soundfile
    sf_dir = os.path.dirname(soundfile.__file__)
    # Look for _soundfile_data or libsndfile
    for sub in ['_soundfile_data', '_soundfile']:
        d = os.path.join(sf_dir, sub)
        if os.path.isdir(d):
            a.datas += [(d, sub)]
except Exception:
    pass

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='hifi-detect',
    debug=False,
    bootloader_ignore_signals=False,
    strip=True,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

# For macOS: create .app bundle (optional, for standalone use without Tauri)
app = BUNDLE(
    exe,
    name='hifi-detect.app',
    icon=None,
    bundle_identifier='com.hifidetector.cli',
)
