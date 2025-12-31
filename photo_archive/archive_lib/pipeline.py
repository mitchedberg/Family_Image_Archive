"""Pipeline orchestration for ingest → assign → thumbs → gallery → publish."""
from __future__ import annotations

import json
import logging
import shutil
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Dict, List, Optional, Sequence

from scripts import init_db as init_db_script

from . import db as db_mod
from .config import AppConfig
from .ingest.scanner import Scanner
from .ingest.assigner import Assigner
from .thumbs import Thumbnailer
from .gallery import build_gallery
from .publish import Publisher, PublishSummary
from .reporting import load_bucket_infos, BucketInfo
from .repair import move_ai_only_to_pending
from .staging import StageManager, load_stage_manifest_map, StagedMeta
from . import hashing

VALID_STEPS = [
    "init_db",
    "repair_ai_only",
    "ingest",
    "assign",
    "thumbs",
    "gallery",
    "publish",
]
DEFAULT_STEPS = ["ingest", "assign", "thumbs", "gallery", "publish"]
VARIANT_ROLES = {"proxy_front", "proxy_back", "ai_front_v1"}
RAW_ROLES = {"raw_front", "raw_back"}


@dataclass(frozen=True)
class RootSpec:
    path: Path
    label: Optional[str]
    role: str  # raw|proxy|ai|manual


@dataclass
class IngestStats:
    total: int
    new: int
    existing: int
    errors: int


@dataclass
class VariantSyncStats:
    copied: int
    skipped: int
    missing: int
    mode: str


class PipelineRunner:
    def __init__(
        self,
        *,
        cfg: AppConfig,
        conn,
        source: str,
        roots: List[RootSpec],
        mode: str,
        steps: List[str],
        publish_enabled: bool,
        publish_options: Dict[str, object],
        plan_only: bool,
        dry_run: bool,
        logger: logging.Logger,
        stage_to_ssd: Optional[Path] = None,
        stage_mode: str = "copy",
        stage_manifest_path: Optional[Path] = None,
        staging_plan: bool = False,
        staging_only: bool = False,
        staged_roots: Optional[List[RootSpec]] = None,
    ) -> None:
        self.cfg = cfg
        self.conn = conn
        self.source = source
        self.roots = roots
        self.mode = mode
        self.steps = steps or DEFAULT_STEPS
        self.publish_enabled = publish_enabled
        self.publish_options = publish_options
        self.plan_only = plan_only
        self.dry_run = dry_run
        self.logger = logger
        self._bucket_cache: Optional[List[BucketInfo]] = None
        self.stage_to_ssd = stage_to_ssd
        self.stage_mode = stage_mode
        self.stage_manifest_path = (
            stage_manifest_path or (self.cfg.reports_dir / "stage_manifest.csv")
        )
        self.staging_plan = staging_plan
        self.staging_only = staging_only
        self.staged_roots_override = staged_roots or []
        self._staging_map: Dict[str, StagedMeta] = {}
        self._ingest_roots: List[RootSpec] = self.roots
        self._timings: Dict[str, float] = {}

    def plan_description(self) -> str:
        lines = ["Pipeline plan:"]
        lines.append(f"  Source: {self.source}")
        lines.append(f"  Steps: {', '.join(self.steps)}")
        lines.append(f"  Mode: {self.mode}")
        lines.append(f"  Publish enabled: {self.publish_enabled}")
        if self.stage_to_ssd:
            lines.append(f"  Stage to SSD: {self.stage_to_ssd} (mode={self.stage_mode})")
        for idx, entry in enumerate(self.roots, start=1):
            lines.append(
                f"  Root {idx}: {entry.path} (label={entry.label or 'n/a'}, role={entry.role.upper()})"
            )
        return "\n".join(lines)

    def run(self) -> Dict[str, object]:
        summary: Dict[str, object] = {
            "run_at": datetime.now(timezone.utc).isoformat(),
            "source": self.source,
            "roots": [
                {"path": str(entry.path), "label": entry.label, "role": entry.role}
                for entry in self.roots
            ],
            "steps": self.steps,
            "mode": self.mode,
            "dry_run": self.dry_run,
        }
        if not self._apply_staging(summary):
            summary["timings"] = self._timings
            self._write_summary_file(summary)
            self._write_ingest_summary(summary)
            return summary
        summary["ingest_roots"] = [
            {"path": str(entry.path), "label": entry.label, "role": entry.role}
            for entry in self._ingest_roots
        ]
        for step in self.steps:
            if step == "init_db":
                summary["init_db"] = self._time_step("init_db", self._run_init_db)
            elif step == "repair_ai_only":
                summary["repair_ai_only"] = self._time_step("repair_ai_only", self._run_repair_ai_only)
            elif step == "ingest":
                ingest_stats = self._time_step("ingest", self._run_ingest)
                summary["ingest"] = asdict(ingest_stats)
            elif step == "assign":
                assign_summary = self._time_step("assign", self._run_assign)
                summary["assign"] = asdict(assign_summary)
                if self.mode != "reference" and not self.dry_run:
                    summary["variant_copy"] = asdict(self._time_step("variant_copy", self._sync_variants))
            elif step == "thumbs":
                summary["thumbs"] = self._time_step("thumbs", self._run_thumbs)
            elif step == "gallery":
                summary["gallery"] = self._time_step("gallery", self._run_gallery)
            elif step == "publish":
                if self.publish_enabled:
                    summary["publish"] = self._time_step("publish", self._run_publish)
                else:
                    self.logger.info("Publish step requested but publish flag disabled; skipping.")
        summary["timings"] = self._timings
        self._write_summary_file(summary)
        self._write_ingest_summary(summary)
        return summary

    def _run_ingest(self) -> IngestStats:
        scanner = Scanner(
            self.conn,
            source=self.source,
            dry_run=self.dry_run,
            reports_dir=self.cfg.reports_dir,
            logger=self.logger,
        )
        root_paths = [entry.path for entry in self._ingest_roots]
        if not root_paths:
            raise RuntimeError("Ingest step requested but no roots were provided")
        label_map = {entry.path: entry.label for entry in self._ingest_roots}
        records = scanner.scan_roots(
            root_paths,
            root_labels=label_map,
            staging_map=self._staging_map if self._staging_map else None,
        )
        total = len(records)
        new_count = sum(1 for r in records if r.status == "new")
        existing = sum(1 for r in records if r.status == "existing")
        errors = sum(1 for r in records if r.status == "error")
        return IngestStats(total=total, new=new_count, existing=existing, errors=errors)

    def _run_assign(self):
        assigner = Assigner(
            self.conn,
            self.cfg,
            logger=self.logger,
            dry_run=self.dry_run,
        )
        summary = assigner.run(source=self.source)
        self._bucket_cache = None
        return summary

    def _run_init_db(self) -> Dict[str, object]:
        if self.plan_only:
            self.logger.info("Plan-only: would initialize DB schema at %s", self.cfg.db_path)
            return {"initialized": False, "plan_only": True}
        if self.dry_run:
            self.logger.info("Dry-run: skipping DB schema init at %s", self.cfg.db_path)
            return {"initialized": False, "dry_run": True}
        db_mod.execute_script(self.conn, init_db_script.CREATE_STATEMENTS)
        self.logger.info("DB schema ensured at %s", self.cfg.db_path)
        return {"initialized": True}

    def _run_repair_ai_only(self) -> Dict[str, object]:
        if self.plan_only:
            self.logger.info("Plan-only: would run AI-only repair")
            return {"run": False, "plan_only": True}
        summary = move_ai_only_to_pending(
            self.conn,
            self.cfg,
            source=self.source,
            logger=self.logger,
            dry_run=self.dry_run,
        )
        return {
            "buckets_considered": summary.buckets_considered,
            "buckets_removed": summary.buckets_removed,
            "variants_moved": summary.variants_moved,
            "dry_run": summary.dry_run,
        }

    def _sync_variants(self) -> VariantSyncStats:
        infos = self._get_bucket_infos()
        if self.mode == "copy_variants":
            roles = VARIANT_ROLES
        elif self.mode == "copy_all":
            roles = VARIANT_ROLES | RAW_ROLES
        else:
            return VariantSyncStats(copied=0, skipped=0, missing=0, mode=self.mode)
        copied = skipped = missing = 0
        for info in infos:
            bucket_dir = self.cfg.buckets_dir / f"bkt_{info.bucket_prefix}"
            for variant in info.variants:
                role = variant.get("role")
                if role not in roles:
                    continue
                source_path = Path(variant["path"])
                if not source_path.exists():
                    missing += 1
                    self.logger.warning("Variant source missing: %s", source_path)
                    continue
                dest_dir = bucket_dir / "variants" / role
                dest_dir.mkdir(parents=True, exist_ok=True)
                dest_path = dest_dir / source_path.name
                if dest_path.exists():
                    try:
                        if hashing.sha256_for_file(dest_path) == hashing.sha256_for_file(source_path):
                            skipped += 1
                            continue
                    except OSError:
                        pass
                    dest_path = dest_dir / f"{source_path.stem}_{hashing.sha256_for_file(source_path)[:8]}{source_path.suffix}"
                shutil.copy2(source_path, dest_path)
                copied += 1
        return VariantSyncStats(copied=copied, skipped=skipped, missing=missing, mode=self.mode)

    def _run_thumbs(self) -> Dict[str, int]:
        infos = self._get_bucket_infos()
        if self.dry_run:
            self.logger.info("Would generate thumbnails for %d buckets", len(infos))
            return {"buckets": len(infos), "skipped": True}
        thumb = Thumbnailer(self.cfg, logger=self.logger, force=False)
        for info in infos:
            thumb.generate(info.bucket_id, list(info.variants))
        return {"buckets": len(infos), "skipped": False}

    def _run_gallery(self) -> Dict[str, str]:
        if self.dry_run:
            self.logger.info("Would rebuild gallery")
            return {"output": str(self.cfg.staging_root / "02_WORKING_BUCKETS/views/qc_site")}
        build_gallery(self.cfg, self.conn, source=self.source, logger=self.logger)
        return {"output": str(self.cfg.staging_root / "02_WORKING_BUCKETS/views/qc_site")}

    def _run_publish(self) -> Dict[str, object]:
        publisher = Publisher(
            self.cfg,
            self.conn,
            logger=self.logger,
            prefer_ai=bool(self.publish_options.get("prefer_ai")),
            include_ai_only=bool(self.publish_options.get("include_ai_only")),
            keywords=bool(self.publish_options.get("keywords")),
            limit=self.publish_options.get("limit"),
            bucket_prefix=self.publish_options.get("bucket_prefix"),
            prune=bool(self.publish_options.get("prune")),
            dry_run=self.dry_run,
        )
        summary: PublishSummary = publisher.run(source=self.source)
        return {
            "published": summary.published,
            "skipped": summary.skipped,
            "relpaths": summary.relpaths,
        }

    def _get_bucket_infos(self) -> List[BucketInfo]:
        if self._bucket_cache is None:
            self._bucket_cache = load_bucket_infos(self.conn, self.cfg, source=self.source)
        return self._bucket_cache

    def _write_summary_file(self, summary: Dict[str, object]) -> None:
        path = self.cfg.reports_dir / "pipeline_last_run.json"
        if self.plan_only:
            return
        with path.open("w", encoding="utf-8") as handle:
            json.dump(summary, handle, indent=2)

    def _write_ingest_summary(self, summary: Dict[str, object]) -> None:
        if self.plan_only:
            return
        data = {
            "run_at": summary.get("run_at"),
            "source": summary.get("source"),
            "timings": summary.get("timings", {}),
            "stage": summary.get("stage"),
            "ingest": summary.get("ingest"),
            "assign": summary.get("assign"),
            "thumbs": summary.get("thumbs"),
            "gallery": summary.get("gallery"),
            "publish": summary.get("publish"),
        }
        path = self.cfg.reports_dir / "ingest_summary.json"
        with path.open("w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2)

    def _time_step(self, name: str, func):
        start = perf_counter()
        result = func()
        self._timings[name] = self._timings.get(name, 0.0) + (perf_counter() - start)
        return result

    def _apply_staging(self, summary: Dict[str, object]) -> bool:
        if self.stage_to_ssd:
            stage_plan_mode = self.staging_plan or self.plan_only
            stage_summary, stage_map, staged_roots = self._time_step(
                "stage", lambda: self._run_stage_manager(stage_plan_mode)
            )
            summary["stage"] = stage_summary
            if self.staging_plan or self.staging_only or self.plan_only:
                return False
            self._staging_map = stage_map
            self._ingest_roots = staged_roots
        elif self.staged_roots_override:
            self._ingest_roots = self.staged_roots_override
            manifest_map = load_stage_manifest_map(
                self.stage_manifest_path, [spec.path for spec in self._ingest_roots]
            )
            self._staging_map = manifest_map
        else:
            self._ingest_roots = self.roots
            self._staging_map = {}
        return True

    def _run_stage_manager(self, plan_override: Optional[bool] = None):
        requests = [(entry.path, entry.label or entry.path.name) for entry in self.roots]
        manager = StageManager(
            self.conn,
            source=self.source,
            stage_root=self.stage_to_ssd,
            stage_mode=self.stage_mode,
            manifest_path=self.stage_manifest_path,
            logger=self.logger,
            plan_only=plan_override if plan_override is not None else self.staging_plan,
        )
        stage_summary, stage_map, staged_specs = manager.run(requests)
        staged_roots = [
            RootSpec(path=path, label=label, role="staged") for path, label in staged_specs
        ]
        return stage_summary.to_dict(), stage_map, staged_roots
