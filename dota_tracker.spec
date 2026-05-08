# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller spec for Dota 2 Tracker
#
# Build:
#   pip install pyinstaller
#   pyinstaller dota_tracker.spec
#
# Output: dist/dota-tracker/
#   dota-tracker.exe   ← double-click to run
#   static/            ← dashboard HTML (bundled)
#   data/              ← created on first run
#   friends.json       ← user edits this to add their Steam IDs
#
# Zip dist/dota-tracker/ and upload to GitHub Releases.

import sys
from pathlib import Path

ROOT = Path(SPECPATH)

# ── Source files to bundle alongside the exe ─────────────────────────────────
datas = [
    (str(ROOT / "static"), "static"),
]

# Bundle the template, never the real friends.json (which contains personal IDs)
template = ROOT / "fill_this_first_friends.json"
if template.exists():
    datas.append((str(template), "."))

# Calibrated model data — bundle everything in data/ except the large match cache
DATA_DIR = ROOT / "data"
DATA_FILES = [
    "model_weights.json",
    "hero_matchups.json",
    "hero_global_stats.json",
    "hero_global_stats_stratz.json",
    "hero_global_stats_merged.json",
    "player_role_stats.json",
    "diff_player_x_hero.parquet",
    "diff_player_x_role.parquet",
    "diff_player_x_player.parquet",
    "baselines.json",
]
for fname in DATA_FILES:
    p = DATA_DIR / fname
    if p.exists():
        datas.append((str(p), "data"))

# ── Hidden imports that PyInstaller's static analysis misses ─────────────────
hidden = [
    # uvicorn loads these dynamically via importlib
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.loops.asyncio",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    "uvicorn.lifespan.off",
    # anyio backend selected at runtime
    "anyio._backends._asyncio",
    # fastapi / starlette internals
    "fastapi.routing",
    "starlette.routing",
    "starlette.middleware.cors",
    # pandas parquet support
    "pyarrow",
    "pyarrow.parquet",
    # pydantic v2 core
    "pydantic_core",
    "pydantic_settings",
]

a = Analysis(
    ["launcher.py"],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # not needed at runtime
        "matplotlib", "notebook", "jupyter", "IPython",
        "scipy",        # only used in notebook calibration
        "pyarrow.tests",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,     # --onedir: keep dlls in the folder, not embedded
    name="dota-tracker",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,              # keep console so users see startup message / errors
    disable_windowed_traceback=False,
    argv_emulation=False,
    icon=None,                 # add an .ico path here if you have one
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="dota-tracker",       # → dist/dota-tracker/
)
