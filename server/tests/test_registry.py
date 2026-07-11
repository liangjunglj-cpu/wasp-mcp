"""Registry tests — no Grasshopper required."""

import pytest

from registry import (
    RegistryLookupError,
    WaspRegistry,
    default_userobjects_dir,
    guess_category,
    key_from_filename,
    normalize,
)

REAL_DIR = default_userobjects_dir()
real_dir_exists = REAL_DIR.is_dir() and any(REAL_DIR.glob("Wasp_*.ghuser"))


# ── key derivation ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("filename,key", [
    ("Wasp_Basic Part.ghuser", "basic_part"),
    ("Wasp_Connection From Plane.ghuser", "connection_from_plane"),
    ("Wasp_Rule From Text.ghuser", "rule_from_text"),
    ("Wasp_Stochastic Aggregation.ghuser", "stochastic_aggregation"),
    ("Wasp_Field-driven Aggregation.ghuser", "field_driven_aggregation"),
    ("Wasp_Graph-Grammar Aggregation.ghuser", "graph_grammar_aggregation"),
    ("Wasp_Get Part Geometry.ghuser", "get_part_geometry"),
    ("Wasp_DisCo Player.ghuser", "disco_player"),
    ("Wasp_Rule.ghuser", "rule"),
])
def test_key_from_filename(filename, key):
    assert key_from_filename(filename) == key


def test_normalize_collapses_separators():
    assert normalize("Field - Driven   Aggregation") == "field_driven_aggregation"


# ── category guessing ──────────────────────────────────────────────────────


@pytest.mark.parametrize("key,category", [
    ("basic_part", "part"),
    ("advanced_part", "part"),
    ("connection_from_plane", "connection"),
    ("rule_from_text", "rule"),
    ("stochastic_aggregation", "aggregation"),
    ("field_driven_aggregation", "field"),
    ("disco_player", "disco"),
    ("save_graph_to_file", "util"),
    ("collider", "part"),
])
def test_guess_category(key, category):
    assert guess_category(key) == category


# ── synthetic directory scan ───────────────────────────────────────────────


def _make_fake_dir(tmp_path):
    names = [
        "Wasp_Basic Part.ghuser",
        "Wasp_Stochastic Aggregation.ghuser",
        "Wasp_Field-driven Aggregation.ghuser",
        "Wasp_Rule From Text.ghuser",
        "NotWasp_Thing.ghuser",       # wrong prefix: excluded
        "Wasp_Readme.txt",            # wrong suffix: excluded
    ]
    for n in names:
        (tmp_path / n).write_bytes(b"")
    return tmp_path


def test_scan_synthetic_dir(tmp_path):
    reg = WaspRegistry(_make_fake_dir(tmp_path))
    entries = reg.scan()
    assert set(entries) == {
        "basic_part", "stochastic_aggregation",
        "field_driven_aggregation", "rule_from_text",
    }
    assert entries["basic_part"].path.endswith("Wasp_Basic Part.ghuser")
    assert entries["stochastic_aggregation"].category == "aggregation"


def test_scan_missing_dir_is_empty(tmp_path):
    reg = WaspRegistry(tmp_path / "does_not_exist")
    assert reg.scan() == {}


# ── fuzzy lookup ───────────────────────────────────────────────────────────


def test_lookup_exact_and_fuzzy(tmp_path):
    reg = WaspRegistry(_make_fake_dir(tmp_path))
    reg.scan()
    assert reg.lookup("basic_part").key == "basic_part"
    assert reg.lookup("Basic Part").key == "basic_part"
    assert reg.lookup("Wasp_Basic Part.ghuser").key == "basic_part"
    # substring fuzz
    assert reg.lookup("stochastic").key == "stochastic_aggregation"
    assert reg.lookup("rule from text").key == "rule_from_text"
    # hyphen/space normalization
    assert reg.lookup("Field-driven Aggregation").key == "field_driven_aggregation"
    # token-subset fuzz
    assert reg.lookup("field aggregation").key == "field_driven_aggregation"


def test_lookup_failure_has_suggestions(tmp_path):
    reg = WaspRegistry(_make_fake_dir(tmp_path))
    reg.scan()
    with pytest.raises(RegistryLookupError) as excinfo:
        reg.lookup("voronoi_cupcake")
    assert excinfo.value.name == "voronoi_cupcake"
    assert isinstance(excinfo.value.suggestions, list)


# ── real machine scan (skipped where Wasp is not installed) ────────────────


@pytest.mark.skipif(not real_dir_exists,
                    reason="Wasp UserObjects not installed on this machine")
def test_real_scan_finds_wasp_components():
    reg = WaspRegistry()
    entries = reg.scan()
    assert len(entries) >= 40, (
        f"expected >=40 Wasp entries in {reg.directory}, got {len(entries)}"
    )


@pytest.mark.skipif(not real_dir_exists,
                    reason="Wasp UserObjects not installed on this machine")
def test_real_registry_has_macro_dependencies():
    """Every registry key the macros depend on must exist on this machine."""
    reg = WaspRegistry()
    entries = reg.scan()
    for key in (
        "basic_part",
        "connection_from_plane",
        "rule_from_text",
        "stochastic_aggregation",
        "field_driven_aggregation",
        "graph_grammar_aggregation",
        "get_part_geometry",
        "deconstruct_part",
    ):
        assert key in entries, f"macro dependency {key!r} missing from registry"


@pytest.mark.skipif(not real_dir_exists,
                    reason="Wasp UserObjects not installed on this machine")
def test_real_fuzzy_lookup():
    reg = WaspRegistry()
    reg.scan()
    assert reg.lookup("stochastic").key == "stochastic_aggregation"
    assert reg.lookup("basic part").key == "basic_part"
    assert reg.lookup("graph grammar").key == "graph_grammar_aggregation"
