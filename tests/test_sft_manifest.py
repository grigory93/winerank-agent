"""Tests for SFT manifest loading, generation, and saving."""
import pytest

from winerank.sft.manifest import generate_manifest, get_or_create_manifest, load_manifest, save_manifest
from winerank.sft.schemas import Manifest, ManifestEntry


# ---------------------------------------------------------------------------
# generate_manifest
# ---------------------------------------------------------------------------


def test_generate_manifest_from_pdfs(tmp_path):
    # Create dummy PDF and HTML files
    (tmp_path / "wine-list.pdf").write_bytes(b"%PDF fake")
    (tmp_path / "another-list.html").write_text("<html></html>", encoding="utf-8")

    manifest = generate_manifest(tmp_path)
    assert len(manifest.lists) == 2

    ids = [e.list_id for e in manifest.lists]
    types = {e.list_id: e.file_type for e in manifest.lists}
    assert any(t == "pdf" for t in types.values())
    assert any(t == "html" for t in types.values())


def test_generate_manifest_empty_dir(tmp_path):
    manifest = generate_manifest(tmp_path)
    assert manifest.lists == []


def test_generate_manifest_unique_ids(tmp_path):
    # Two files that might produce the same slug
    (tmp_path / "wine.pdf").write_bytes(b"%PDF")
    (tmp_path / "wine.html").write_text("<html></html>")
    manifest = generate_manifest(tmp_path)
    ids = [e.list_id for e in manifest.lists]
    assert len(ids) == len(set(ids)), "Duplicate list IDs found"


def test_generate_manifest_restaurant_name(tmp_path):
    (tmp_path / "eleven-madison-park.pdf").write_bytes(b"%PDF")
    manifest = generate_manifest(tmp_path)
    name = manifest.lists[0].restaurant_name
    assert "Eleven" in name or "eleven" in name.lower()


# ---------------------------------------------------------------------------
# save_manifest / load_manifest round-trip
# ---------------------------------------------------------------------------


def test_save_and_load_manifest(tmp_path):
    manifest = Manifest(
        lists=[
            ManifestEntry(
                list_id="test-list",
                restaurant_name="Test Restaurant",
                file_path="data/examples/test.pdf",
                file_type="pdf",
            ),
            ManifestEntry(
                list_id="fiola-html",
                restaurant_name="Fiola",
                file_path="data/examples/Fiola-wine-list.html",
                file_type="html",
                notes="SPA-rendered HTML",
            ),
        ]
    )
    manifest_path = tmp_path / "manifest.yaml"
    save_manifest(manifest, manifest_path)
    assert manifest_path.exists()

    loaded = load_manifest(manifest_path)
    assert len(loaded.lists) == 2
    assert loaded.lists[0].list_id == "test-list"
    assert loaded.lists[1].notes == "SPA-rendered HTML"
    assert loaded.lists[1].file_type == "html"


def test_load_manifest_not_found(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_manifest(tmp_path / "nonexistent.yaml")


def test_load_manifest_invalid_yaml(tmp_path):
    bad_yaml = tmp_path / "bad.yaml"
    bad_yaml.write_text("not: a: valid: manifest: structure", encoding="utf-8")
    with pytest.raises((ValueError, Exception)):
        load_manifest(bad_yaml)


def test_load_manifest_missing_list_id(tmp_path):
    bad_manifest = tmp_path / "manifest.yaml"
    bad_manifest.write_text(
        "lists:\n  - restaurant_name: Test\n    file_path: test.pdf\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        load_manifest(bad_manifest)


# ---------------------------------------------------------------------------
# Manifest.get_entry
# ---------------------------------------------------------------------------


def test_manifest_get_entry_found():
    manifest = Manifest(
        lists=[
            ManifestEntry(
                list_id="quince",
                restaurant_name="Quince",
                file_path="quince.pdf",
                file_type="pdf",
            )
        ]
    )
    entry = manifest.get_entry("quince")
    assert entry is not None
    assert entry.restaurant_name == "Quince"


def test_manifest_get_entry_not_found():
    manifest = Manifest(lists=[])
    assert manifest.get_entry("nonexistent") is None


# ---------------------------------------------------------------------------
# get_or_create_manifest
# ---------------------------------------------------------------------------


def test_get_or_create_manifest_creates_new(tmp_path):
    examples = tmp_path / "examples"
    examples.mkdir()
    (examples / "wine.pdf").write_bytes(b"%PDF")

    manifest_path = tmp_path / "manifest.yaml"
    manifest = get_or_create_manifest(manifest_path, examples_dir=examples)
    assert len(manifest.lists) == 1


def test_get_or_create_manifest_loads_existing(tmp_path):
    # Create a manifest with 1 entry
    manifest = Manifest(
        lists=[
            ManifestEntry(
                list_id="x",
                restaurant_name="X",
                file_path="x.pdf",
                file_type="pdf",
            )
        ]
    )
    manifest_path = tmp_path / "manifest.yaml"
    save_manifest(manifest, manifest_path)

    loaded = get_or_create_manifest(manifest_path)
    assert len(loaded.lists) == 1
    assert loaded.lists[0].list_id == "x"


def test_get_or_create_manifest_no_examples_dir_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        get_or_create_manifest(tmp_path / "nonexistent.yaml")
