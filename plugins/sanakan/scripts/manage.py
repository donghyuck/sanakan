#!/usr/bin/env python3
"""Execute the packaged Sanakan runtime, or its source checkout during development."""
from pathlib import Path
import sys

plugin = Path(__file__).resolve().parents[1]
runtime = plugin / 'runtime'
if not (runtime / 'sanakan/__main__.py').is_file():
    runtime = plugin.parents[1]
if not (runtime / 'sanakan/__main__.py').is_file():
    raise SystemExit('Sanakan runtime missing; install the complete plugin ZIP')
sys.path.insert(0, str(runtime))
from sanakan.__main__ import main
raise SystemExit(main())
