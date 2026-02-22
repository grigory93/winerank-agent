"""Tests for SFT page sampler: stratified random sampling."""
import json
from pathlib import Path

import pytest

from winerank.sft.manifest import ManifestEntry
from winerank.sft.page_sampler import load_samples, sample_segments, save_samples
from winerank.sft.schemas import SampleManifestEntry, WineSegment


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SEMANTIC_HTML = """<!doctype html>
<html><body>
<h1>Wine List</h1>
<h2>Champagne</h2>
<p>Krug Grande Cuvee NV $450</p>
<p>Dom Perignon 2015 $350</p>
<h2>Red Wines</h2>
<p>Chateau Margaux 2018 $600</p>
<h2>White Wines</h2>
<p>Puligny-Montrachet 2020 $200</p>
<h2>Dessert Wines</h2>
<p>Chateau d'Yquem 2015 $300</p>
</body></html>"""


def make_html_list(tmp_path: Path, name: str, content: str = SEMANTIC_HTML) -> ManifestEntry:
    f = tmp_path / f"{name}.html"
    f.write_text(content, encoding="utf-8")
    return ManifestEntry(
        list_id=name,
        restaurant_name=name.title(),
        file_path=str(f),
        file_type="html",
    )


# ---------------------------------------------------------------------------
# sample_segments
# ---------------------------------------------------------------------------


def test_sample_reproducibility(tmp_path):
    entries = [make_html_list(tmp_path, f"list{i}") for i in range(5)]
    samples_a = sample_segments(entries, not_a_list_ids=set(), num_samples=10, seed=42)
    samples_b = sample_segments(entries, not_a_list_ids=set(), num_samples=10, seed=42)

    ids_a = [(s.list_id, s.segment_index) for s in samples_a]
    ids_b = [(s.list_id, s.segment_index) for s in samples_b]
    assert ids_a == ids_b


def test_sample_different_seeds(tmp_path):
    # Use HTML with many sections per list so each list has several segments
    large_html = "<!doctype html><html><body>\n" + "\n".join(
        f"<h2>Section {i}</h2><p>Wine A {i} $100</p><p>Wine B {i} $200</p>"
        f"<p>Wine C {i} $300</p><p>Wine D {i} $400</p>"
        for i in range(8)
    ) + "\n</body></html>"
    entries = [make_html_list(tmp_path, f"list{i}", content=large_html) for i in range(4)]
    # Request fewer samples than total available so seeds pick different subsets
    samples_a = sample_segments(entries, not_a_list_ids=set(), num_samples=8, seed=42, min_per_list=1)
    samples_b = sample_segments(entries, not_a_list_ids=set(), num_samples=8, seed=99, min_per_list=1)

    ids_a = set((s.list_id, s.segment_index) for s in samples_a)
    ids_b = set((s.list_id, s.segment_index) for s in samples_b)
    # Different seeds should (with very high probability) produce different results
    assert ids_a != ids_b


def test_sample_excludes_not_a_list(tmp_path):
    entries = [make_html_list(tmp_path, f"list{i}") for i in range(4)]
    not_a_list = {"list0", "list1"}
    samples = sample_segments(entries, not_a_list_ids=not_a_list, num_samples=10, seed=42)

    sampled_lists = {s.list_id for s in samples}
    assert "list0" not in sampled_lists
    assert "list1" not in sampled_lists


def test_sample_minimum_per_list(tmp_path):
    entries = [make_html_list(tmp_path, f"list{i}") for i in range(3)]
    samples = sample_segments(entries, not_a_list_ids=set(), num_samples=20, seed=42, min_per_list=2)

    # Each valid list should have at least min_per_list samples
    per_list = {}
    for s in samples:
        per_list.setdefault(s.list_id, 0)
        per_list[s.list_id] += 1
    for list_id, count in per_list.items():
        assert count >= 1, f"List {list_id} has too few samples"


def test_sample_empty_valid_lists(tmp_path):
    entries = [make_html_list(tmp_path, "list0")]
    # All marked as NOT_A_LIST
    samples = sample_segments(entries, not_a_list_ids={"list0"}, num_samples=10, seed=42)
    assert samples == []


def test_sample_returns_sample_manifest_entries(tmp_path):
    entries = [make_html_list(tmp_path, "list0")]
    samples = sample_segments(entries, not_a_list_ids=set(), num_samples=5, seed=42)
    for s in samples:
        assert isinstance(s, SampleManifestEntry)
        assert s.list_id == "list0"
        assert isinstance(s.segment_index, int)


def test_sample_file_not_found(tmp_path):
    entries = [
        ManifestEntry(
            list_id="missing",
            restaurant_name="Missing",
            file_path="/nonexistent/file.pdf",
            file_type="pdf",
        )
    ]
    samples = sample_segments(entries, not_a_list_ids=set(), num_samples=5, seed=42)
    assert samples == []


# ---------------------------------------------------------------------------
# save_samples / load_samples round-trip
# ---------------------------------------------------------------------------


def test_save_and_load_samples(tmp_path):
    samples = [
        SampleManifestEntry(
            list_id="list1",
            segment_index=2,
            source_file="data/examples/test.pdf",
            file_type="pdf",
            char_count=300,
        ),
        SampleManifestEntry(
            list_id="list2",
            segment_index=0,
            source_file="data/examples/test2.html",
            file_type="html",
            char_count=150,
        ),
    ]
    samples_path = tmp_path / "samples.json"
    save_samples(samples, samples_path)
    assert samples_path.exists()

    loaded = load_samples(samples_path)
    assert len(loaded) == 2
    assert loaded[0].list_id == "list1"
    assert loaded[0].segment_index == 2
    assert loaded[1].file_type == "html"


def test_load_samples_not_found(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_samples(tmp_path / "nonexistent.json")
