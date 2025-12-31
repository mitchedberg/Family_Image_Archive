"""Static HTML gallery builder for bucket QC."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import List

from .config import AppConfig
from .reporting import BucketInfo, load_bucket_infos
from .ingest.assigner import BUCKET_PREFIX_LENGTH

INDEX_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
  <meta charset='utf-8'>
  <title>Bucket QC</title>
  <style>
    body {{ font-family: sans-serif; margin: 20px; }}
    .filters label {{ margin-right: 12px; }}
    .bucket-list {{ display: flex; flex-wrap: wrap; gap: 16px; }}
    .bucket-card {{ border: 1px solid #ccc; padding: 12px; width: 220px; }}
    .bucket-card img {{ max-width: 200px; height: auto; display: block; }}
  </style>
</head>
<body>
  <h1>Bucket QC</h1>
  <div class="filters">
    <label><input type="checkbox" data-filter="needs_review"> Needs Review</label>
    <label><input type="checkbox" data-filter="ai_only"> AI Only</label>
    <label><input type="checkbox" data-filter="missing_back"> Missing Back</label>
    <label><input type="checkbox" data-filter="missing_front"> Missing Front</label>
    <label><input type="checkbox" data-filter="has_ai"> Has AI</label>
    <label><input type="checkbox" data-filter="preferred_set"> Preferred Set</label>
  </div>
  <div class="bucket-list">
    {cards}
  </div>
<script>
  const filters = document.querySelectorAll('[data-filter]');
  filters.forEach(filter => {{
    filter.addEventListener('change', () => {{
      const active = Array.from(filters).filter(f => f.checked).map(f => f.dataset.filter);
      document.querySelectorAll('.bucket-card').forEach(card => {{
        const flags = card.dataset.flags.split(',');
        const show = active.every(flag => flags.includes(flag));
        card.style.display = show ? 'block' : 'none';
      }});
    }});
  }});
</script>
</body>
</html>
"""

BUCKET_CARD_TEMPLATE = """<div class='bucket-card' data-flags="{flags}">
  <a href="buckets/{prefix}.html"><strong>{prefix}</strong></a><br>
  <span>{source} | {group_key}</span><br>
  <img src="../buckets/{prefix}/derived/thumb_front.jpg" alt="thumb">
</div>"""

DETAIL_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
  <meta charset='utf-8'>
  <title>{prefix}</title>
  <style>
    body {{ font-family: sans-serif; margin: 20px; }}
    .thumbs img {{ max-width: 320px; margin-right: 12px; }}
    .meta {{ margin-bottom: 20px; }}
    .files table {{ border-collapse: collapse; width: 100%; }}
    .files th, .files td {{ border: 1px solid #ccc; padding: 8px; }}
  </style>
</head>
<body>
  <a href="../index.html">Back to index</a>
  <h1>Bucket {prefix}</h1>
  <div class="meta">
    <div>Source: {source}</div>
    <div>Group Key: {group_key}</div>
    <div>Needs Review: {needs_review}</div>
    <div>Roles: {roles}</div>
    <div>Flags: {flags}</div>
    <div>Preferred Variant: {preferred_variant}</div>
  </div>
  <div class="thumbs">
    {thumb_imgs}
  </div>
  <div class="files">
    <table>
      <thead><tr><th>Role</th><th>Primary</th><th>Relative Path</th><th>Open</th></tr></thead>
      <tbody>
        {rows}
      </tbody>
    </table>
  </div>
</body>
</html>
"""


def build_gallery(cfg: AppConfig, conn, *, source: str | None, logger: logging.Logger) -> None:
    infos = load_bucket_infos(conn, cfg, source=source)
    view_root = cfg.staging_root / "02_WORKING_BUCKETS" / "views" / "qc_site"
    view_root.mkdir(parents=True, exist_ok=True)
    bucket_pages_dir = view_root / "buckets"
    bucket_pages_dir.mkdir(parents=True, exist_ok=True)
    index_records: List[dict] = []
    cards: List[str] = []
    for info in infos:
        prefix = info.bucket_prefix or info.bucket_id[:BUCKET_PREFIX_LENGTH]
        bucket_dir = cfg.buckets_dir / f"bkt_{prefix}"
        derived_dir = bucket_dir / "derived"
        roles = sorted(info.roles.keys())
        has_proxy_front = "proxy_front" in info.roles
        has_raw_front = "raw_front" in info.roles
        has_ai = "ai_front_v1" in info.roles
        missing_front = not (has_proxy_front or has_raw_front)
        missing_back = not any(role in info.roles for role in ("raw_back", "proxy_back"))
        ai_only = missing_front and has_ai
        flags = []
        if info.needs_review:
            flags.append("needs_review")
        if ai_only:
            flags.append("ai_only")
        if missing_back:
            flags.append("missing_back")
        if missing_front:
            flags.append("missing_front")
        if has_ai:
            flags.append("has_ai")
        if info.preferred_variant:
            flags.append("preferred_set")
        flag_str = ",".join(flags or ["none"])
        cards.append(
            BUCKET_CARD_TEMPLATE.format(
                prefix=f"bkt_{prefix}",
                source=info.source,
                group_key=info.group_key,
                flags=flag_str,
            )
        )
        thumb_imgs = []
        for name in ("thumb_front.jpg", "thumb_proxy_front.jpg", "thumb_ai_front_v1.jpg", "thumb_back.jpg"):
            thumb_path = bucket_dir / "derived" / name
            if thumb_path.exists():
                rel = Path("../../buckets") / f"bkt_{prefix}" / "derived" / name
                thumb_imgs.append(f"<img src='{rel}' alt='{name}'>")
        rows = []
        for variant in info.variants:
            file_path = Path(variant["path"])
            rows.append(
                f"<tr><td>{variant['role']}</td><td>{variant['is_primary']}</td>"
                f"<td>{variant['original_relpath']}</td><td><a href='file://{file_path}'>Open</a></td></tr>"
            )
        detail_html = DETAIL_TEMPLATE.format(
            prefix=f"bkt_{prefix}",
            source=info.source,
            group_key=info.group_key,
            needs_review=info.needs_review,
            roles=", ".join(roles),
            flags=", ".join(flags) or "none",
            preferred_variant=info.preferred_variant or "",
            thumb_imgs="".join(thumb_imgs) or "<em>No thumbnails</em>",
            rows="".join(rows),
        )
        (bucket_pages_dir / f"bkt_{prefix}.html").write_text(detail_html, encoding="utf-8")
        index_records.append(
            {
                "bucket_id": info.bucket_id,
                "bucket_prefix": prefix,
                "source": info.source,
                "group_key": info.group_key,
                "needs_review": info.needs_review,
                "has_ai": has_ai,
                "missing_back": missing_back,
                "missing_front": missing_front,
                "preferred_set": bool(info.preferred_variant),
                "roles": roles,
                "thumbs": [p.name for p in derived_dir.glob("thumb_*.jpg")],
            }
        )
    (cfg.staging_root / "02_WORKING_BUCKETS" / "views" / "qc_index.json").write_text(
        json.dumps(index_records, indent=2),
        encoding="utf-8",
    )
    index_html = INDEX_TEMPLATE.format(cards="\n".join(cards))
    (view_root / "index.html").write_text(index_html, encoding="utf-8")
    logger.info("Generated QC gallery for %d buckets", len(infos))
