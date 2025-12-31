"""Backfill fastfoto-style hash join keys for non-family_photos buckets."""
from __future__ import annotations

import json
from pathlib import Path

from archive_lib import config as config_mod, db as db_mod

MODULUS = 10**16


def fastfoto_token(sha256_hex: str) -> str:
    first = sha256_hex[:16]
    value = int(first, 16) % MODULUS
    return f"{value:016d}"


def main() -> None:
    cfg = config_mod.load_config()
    conn = db_mod.connect(cfg.db_path)
    rows = conn.execute(
        """
        SELECT b.bucket_id,
               b.bucket_prefix,
               b.source,
               raw.sha256 AS raw_sha,
               proxy.sha256 AS proxy_sha
        FROM buckets b
        LEFT JOIN bucket_files bf_raw
            ON bf_raw.bucket_id = b.bucket_id AND bf_raw.role = 'raw_front'
        LEFT JOIN files raw
            ON raw.sha256 = bf_raw.file_sha256
        LEFT JOIN bucket_files bf_proxy
            ON bf_proxy.bucket_id = b.bucket_id AND bf_proxy.role = 'proxy_front'
        LEFT JOIN files proxy
            ON proxy.sha256 = bf_proxy.file_sha256
        """
    ).fetchall()

    updated_sidecars = 0
    updated_keys = 0
    skipped = 0

    for row in rows:
        source = row["source"] or ""
        if source == "family_photos":
            continue
        sha = row["raw_sha"] or row["proxy_sha"]
        if not sha:
            skipped += 1
            continue
        token = fastfoto_token(sha)
        conn.execute(
            """
            INSERT INTO bucket_join_keys (bucket_id, source, key_type, key_value)
            VALUES (?, ?, 'fastfoto_hash', ?)
            ON CONFLICT(source, key_type, key_value) DO UPDATE SET
                bucket_id=excluded.bucket_id
            """,
            (row["bucket_id"], source, token),
        )
        updated_keys += 1

        bucket_dir = cfg.buckets_dir / f"bkt_{row['bucket_prefix']}"
        sidecar_path = bucket_dir / "sidecar.json"
        if not sidecar_path.exists():
            continue
        try:
            payload = json.loads(sidecar_path.read_text())
        except json.JSONDecodeError:
            continue
        data = payload.setdefault("data", {})
        join_keys = data.setdefault("join_keys", {})
        if join_keys.get("fastfoto_hash") == token:
            continue
        join_keys["fastfoto_hash"] = token
        sidecar_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
        updated_sidecars += 1

    conn.commit()
    print(
        f"Backfill complete: join_keys={updated_keys} sidecars={updated_sidecars} skipped={skipped}"
    )


if __name__ == "__main__":
    main()
