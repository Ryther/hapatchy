"""Exact byte behavior: no fuzzy, ambiguous or unchecked patch application."""

import importlib
from pathlib import Path

import pytest

DIFF = b"--- a/python_scripts/test.py\n+++ b/python_scripts/test.py\n@@ -1,3 +1,3 @@\n first\n-old\n+new\n last\n"
TARGET = "python_scripts/test.py"


def load_engine():
    assert Path("custom_components/hapatchy/patch_engine.py").exists(), (
        "Exact patch engine has not been implemented"
    )
    return importlib.import_module("custom_components.hapatchy.patch_engine").UnifiedDiffEngine()


@pytest.mark.parametrize(
    ("original", "expected", "status"),
    [
        (b"first\nold\nlast\n", b"first\nnew\nlast\n", "applicable"),
        (
            b"prefix\nfirst\nold\nlast\nsuffix\n",
            b"prefix\nfirst\nnew\nlast\nsuffix\n",
            "applicable",
        ),
        (b"first\nnew\nlast\n", b"first\nold\nlast\n", "applied"),
        (b"first\nchanged\nlast\n", None, "conflict"),
        (b"first\r\nold\r\nlast\r\n", b"first\r\nnew\r\nlast\r\n", "applicable"),
        (b"first\nold\nlast\nfirst\nold\nlast\n", None, "conflict"),
        (b"first\nold\nlast\nfirst\nnew\nlast\n", None, "invalid_patch"),
    ],
)
def test_exact_directional_outputs(original, expected, status):
    engine = load_engine()
    parsed = engine.parse(DIFF, TARGET)
    result = engine.inspect(parsed, original)
    assert result.status == status
    assert result.forward_output == (expected if status == "applicable" else None)
    assert result.reverse_output == (expected if status == "applied" else None)


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        DIFF + b"ignored garbage\n",
        DIFF + DIFF,
        DIFF.replace(b"-1,3", b"-1,4"),
        DIFF.replace(b"python_scripts/test.py", b"../outside"),
        DIFF.replace(b"a/python_scripts/test.py", b"/dev/null"),
        DIFF.replace(b"+new", b"+old"),
        b"--- a/python_scripts/test.py\n+++ b/python_scripts/test.py\n@@ -0,0 +1 @@\n+new\n",
        DIFF.replace(b" first\n", b"\n"),
        DIFF.replace(b"last", b"\xff"),
    ],
)
def test_invalid_envelopes_rejected(raw):
    engine = load_engine()
    with pytest.raises(ValueError):
        engine.parse(raw, TARGET)


def test_missing_final_newline():
    engine = load_engine()
    raw = b"--- a/python_scripts/test.py\n+++ b/python_scripts/test.py\n@@ -1,2 +1,2 @@\n first\n-old\n\\ No newline at end of file\n+new\n\\ No newline at end of file\n"
    result = engine.inspect(engine.parse(raw, TARGET), b"first\nold")
    assert result.status == "applicable"
    assert result.forward_output == b"first\nnew"


def test_mixed_endings_cannot_write():
    engine = load_engine()
    result = engine.inspect(engine.parse(DIFF, TARGET), b"first\r\nold\nlast\n")
    assert result.status == "invalid_patch"
    assert result.forward_output is None


def test_parser_cannot_change_cwd_or_call_applicator(monkeypatch):
    engine = load_engine()
    import patch_ng

    def denied(*a, **kw):
        pytest.fail("Third-party applicator called")

    monkeypatch.setattr(patch_ng.PatchSet, "apply", denied)
    monkeypatch.setattr(patch_ng.PatchSet, "revert", denied)
    before = Path.cwd()
    result = engine.inspect(engine.parse(DIFF, TARGET), b"first\nold\nlast\n")
    assert result.forward_output == b"first\nnew\nlast\n"
    assert Path.cwd() == before


def test_repeated_device_attribute_requires_distinguishing_context():
    engine = load_engine()
    raw = b"--- a/python_scripts/test.py\n+++ b/python_scripts/test.py\n@@ -4,3 +4,3 @@\n MODEL_PLUS_UNI: {\n-    use_subdevices: True,\n+    use_subdevices: False,\n },\n"
    original = b"MODEL_OTHER: {\n    use_subdevices: True,\n},\nMODEL_PLUS_UNI: {\n    use_subdevices: True,\n},\nMODEL_LAST: {\n    use_subdevices: True,\n},\n"
    expected = b"MODEL_OTHER: {\n    use_subdevices: True,\n},\nMODEL_PLUS_UNI: {\n    use_subdevices: False,\n},\nMODEL_LAST: {\n    use_subdevices: True,\n},\n"
    assert engine.inspect(engine.parse(raw, TARGET), original).forward_output == expected


def test_multiple_hunks_preserve_unrelated_intervening_lines():
    engine = load_engine()
    raw = b"--- a/python_scripts/test.py\n+++ b/python_scripts/test.py\n@@ -1,2 +1,2 @@\n first\n-old\n+new\n@@ -4,2 +4,2 @@\n second\n-before\n+after\n"
    original = b"prefix\nfirst\nold\nextra\nunrelated\nsecond\nbefore\n"
    assert (
        engine.inspect(engine.parse(raw, TARGET), original).forward_output
        == b"prefix\nfirst\nnew\nextra\nunrelated\nsecond\nafter\n"
    )


def test_context_insertion_and_deletion_are_reversible():
    engine = load_engine()
    raw = b"--- a/python_scripts/test.py\n+++ b/python_scripts/test.py\n@@ -1,2 +1,3 @@\n first\n+inserted\n last\n"
    patch = engine.parse(raw, TARGET)
    assert engine.inspect(patch, b"first\nlast\n").forward_output == b"first\ninserted\nlast\n"
    assert engine.inspect(patch, b"first\ninserted\nlast\n").reverse_output == b"first\nlast\n"


def test_source_and_target_caps():
    engine = load_engine()
    with pytest.raises(ValueError, match="size_limit"):
        engine.parse(b"a" * (2 * 1024 * 1024 + 1), TARGET)
    assert (
        engine.inspect(engine.parse(DIFF, TARGET), b"a" * (16 * 1024 * 1024 + 1)).status
        == "invalid_patch"
    )
