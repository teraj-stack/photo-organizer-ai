# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['/Users/krzysztofjarzyna/.gemini/antigravity/scratch/photo-organizer-ai/packaging/launcher.py'],
    pathex=['/Users/krzysztofjarzyna/.gemini/antigravity/scratch/photo-organizer-ai'],
    binaries=[],
    datas=[('/Users/krzysztofjarzyna/.gemini/antigravity/scratch/photo-organizer-ai/static', 'static')],
    hiddenimports=['uvicorn.logging', 'uvicorn.loops', 'uvicorn.loops.auto', 'uvicorn.protocols', 'uvicorn.protocols.http', 'uvicorn.protocols.http.auto', 'uvicorn.protocols.websockets', 'uvicorn.protocols.websockets.auto', 'uvicorn.lifespan', 'uvicorn.lifespan.on', 'app'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Photo Organizer AI',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['/Users/krzysztofjarzyna/.gemini/antigravity/scratch/photo-organizer-ai/build/AppIcon.icns'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Photo Organizer AI',
)
app = BUNDLE(
    coll,
    name='Photo Organizer AI.app',
    icon='/Users/krzysztofjarzyna/.gemini/antigravity/scratch/photo-organizer-ai/build/AppIcon.icns',
    bundle_identifier='pl.photoorganizer.ai',
)
