# cli/faces_queue.py — map bucket + filename to served asset if it exists
    def _bucket_asset_url(self, bucket_prefix: str, filename: str) -> Optional[str]:
        if not bucket_prefix or not filename:
            return None
        relative_path = f"buckets/bkt_{bucket_prefix}/derived/{filename}"
        if not self._asset_exists(relative_path):
            return None
        return "/" + relative_path

# cli/review.py — find actual file for a variant (raw_back/proxy_back/etc)
    def _find_variant_path(self, bucket_prefix: str, roles: List[str]) -> Optional[Path]:
        bucket_dir = Path(self.directory) / "buckets" / f"bkt_{bucket_prefix}"
        sidecar_path = bucket_dir / "sidecar.json"
        if not sidecar_path.exists():
            return None
        try:
            sidecar = json.loads(sidecar_path.read_text())
        except json.JSONDecodeError:
            return None
        variants = sidecar.get("data", {}).get("variants", [])
        for role in roles:
            for candidate in variants:
                if candidate.get("role") != role:
                    continue
                path_str = candidate.get("path")
                if not path_str:
                    continue
                path = Path(str(path_str))
                if path.exists():
                    return path
        return None
