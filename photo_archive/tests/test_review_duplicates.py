import json
from pathlib import Path

from archive_lib.config import AppConfig
from cli import review


def _make_cfg(tmp_path: Path) -> AppConfig:
    staging = tmp_path / "staging"
    staging.mkdir(parents=True, exist_ok=True)
    reports_dir = staging / "02_WORKING_BUCKETS" / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    buckets_dir = staging / "02_WORKING_BUCKETS" / "buckets"
    config_dir = staging / "02_WORKING_BUCKETS" / "config"
    db_path = staging / "02_WORKING_BUCKETS" / "db.sqlite"
    return AppConfig(
        repo_root=tmp_path,
        staging_root=staging,
        db_path=db_path,
        reports_dir=reports_dir,
        buckets_dir=buckets_dir,
        config_dir=config_dir,
    )


def test_load_duplicate_clusters_reads_match_graph(tmp_path):
    cfg = _make_cfg(tmp_path)
    state_dir = cfg.reports_dir / "phash_test"
    state_dir.mkdir(parents=True, exist_ok=True)
    state_file = state_dir / "phash_review_state.json"
    payload = {
        "aaaa__bbbb": "match",
        "bbbb__cccc": "match",
        "cccc__dddd": "reject",
        "eeee": "match",
        "ffff__ffff": "match",
    }
    state_file.write_text(json.dumps(payload), encoding="utf-8")

    clusters = review._load_duplicate_clusters(cfg)

    assert clusters["aaaa"]["group_id"] == "aaaa"
    assert clusters["bbbb"]["group_size"] == 3
    assert set(clusters["aaaa"]["members"]) == {"bbbb", "cccc"}
    assert set(clusters["bbbb"]["members"]) == {"aaaa", "cccc"}
    assert "dddd" not in clusters
    assert "eeee" not in clusters


def test_attach_duplicate_metadata_embeds_peer_details(tmp_path):
    entries = [
        {
            "bucket_prefix": "aaaa",
            "source": "family_photos",
            "has_ai": True,
            "has_back": False,
            "web_front": "/views/aaaa.jpg",
            "thumb_front": "/thumbs/aaaa.jpg",
        },
        {
            "bucket_prefix": "bbbb",
            "source": "negatives",
            "has_ai": False,
            "has_back": True,
            "thumb_front": "/thumbs/bbbb.jpg",
        },
    ]
    entry_lookup = {entry["bucket_prefix"]: entry for entry in entries}
    clusters = {
        "aaaa": {"group_id": "aaaa", "group_size": 2, "members": ["bbbb"]},
        "bbbb": {"group_id": "aaaa", "group_size": 2, "members": ["aaaa"]},
    }

    review._attach_duplicate_metadata(entries, clusters, entry_lookup)

    dup_a = entries[0]["duplicates"]
    assert dup_a["group_id"] == "aaaa"
    assert dup_a["group_size"] == 2
    assert dup_a["peers"][0]["bucket_prefix"] == "bbbb"
    assert dup_a["peers"][0]["source"] == "negatives"
    assert dup_a["peers"][0]["has_back"] is True

    dup_b = entries[1]["duplicates"]
    assert dup_b["peers"][0]["bucket_prefix"] == "aaaa"
    assert dup_b["peers"][0]["has_ai"] is True
