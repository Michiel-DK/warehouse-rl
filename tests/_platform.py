"""Platform-aware reference values for tests whose numbers depend on the simulator's A* tie-break (docs/PLATFORM.md).

The tag comes from scripts/evaluate.py (platform_tag) so there is one normalisation; evaluate.py never imports tests/.
"""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import evaluate as _ev

EXPECTED_PATH = Path(__file__).with_name("platform_expected.json")


def tag():
    """Current platform tag, e.g. darwin-arm64, linux-x86_64, linux-arm64."""
    return _ev.platform_tag()


def expected(test_name, key):
    """Reference value for this platform. No entry for the current tag -> a visible SkipTest, never a KeyError."""
    t = tag()
    entry = json.loads(EXPECTED_PATH.read_text()).get(test_name, {}).get(t)
    if entry is None or key not in entry:
        raise unittest.SkipTest(f"no {t} reference yet for {test_name}")
    return entry[key]


def results_platform(doc):
    """Platform a results doc was measured on. Files without the field predate it and were all measured on
    darwin-arm64."""
    return doc.get("platform", "darwin-arm64")
