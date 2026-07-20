"""Manifest des Regressions-Korpus: Hashing, Pfad-Aufloesung, Round-Trip."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from docodetect.corpus.manifest import (ImageEntry, Manifest, corpus_root,
                                        sha256_file)


def test_sha256_file_is_stable_and_content_based(tmp_path):
    a, b = tmp_path / "a.bin", tmp_path / "b.bin"
    a.write_bytes(b"doco")
    b.write_bytes(b"doco")
    assert sha256_file(a) == sha256_file(b)
    assert len(sha256_file(a)) == 64
    b.write_bytes(b"detect")
    assert sha256_file(a) != sha256_file(b)


def test_corpus_root_resolves_relative_to_project(tmp_path):
    cfg = {"paths": {"corpus_dir": str(tmp_path / "korpus")}}
    assert corpus_root(cfg) == tmp_path / "korpus"


def test_corpus_root_defaults_when_key_missing():
    root = corpus_root({"paths": {}})
    assert root.name == "Doco_Detect_corpus"


def test_manifest_roundtrip_preserves_entries(tmp_path, monkeypatch):
    path = tmp_path / "manifest.json"
    monkeypatch.setattr("docodetect.corpus.manifest.MANIFEST_PATH", path)
    m = Manifest(
        version=1, generated="2026-07-20T12:00:00",
        sessions={"phase-b": {"tier": 2, "db_verified": 1.0, "n_images": 1}},
        images=[ImageEntry(sha="ab" * 32, session="phase-b", article="LOEFFEL-1",
                           image_rel="phase-b/images/LOEFFEL-1/abababab.png",
                           report_rel="phase-b/reports/abababab.json",
                           label="LOEFFEL-1", verdict="correct", tier=2)])
    m.save()
    back = Manifest.load()
    assert back.version == 1
    assert back.sessions["phase-b"]["tier"] == 2
    assert len(back.images) == 1
    assert back.images[0].article == "LOEFFEL-1"
    assert back.by_sha()["ab" * 32].label == "LOEFFEL-1"


def test_manifest_load_returns_empty_when_absent(tmp_path, monkeypatch):
    monkeypatch.setattr("docodetect.corpus.manifest.MANIFEST_PATH",
                        tmp_path / "fehlt.json")
    m = Manifest.load()
    assert m.images == []
    assert m.sessions == {}


def test_manifest_is_written_sorted_for_stable_diffs(tmp_path, monkeypatch):
    path = tmp_path / "manifest.json"
    monkeypatch.setattr("docodetect.corpus.manifest.MANIFEST_PATH", path)
    mk = lambda sha: ImageEntry(sha=sha, session="s", article="A",
                                image_rel=f"s/images/A/{sha[:8]}.png",
                                report_rel=f"s/reports/{sha[:8]}.json",
                                label="A", verdict="correct", tier=1)
    Manifest(version=1, generated="x", sessions={},
             images=[mk("ff" * 32), mk("00" * 32)]).save()
    shas = [e["sha"] for e in json.loads(path.read_text())["images"]]
    assert shas == sorted(shas)
