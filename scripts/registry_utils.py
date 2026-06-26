CANONICAL_LIFECYCLE_STATUSES = {"active", "superseded", "archived"}
LEGACY_ACTIVE_STATUSES = {"", "accepted", "warning", "unknown", "active"}
LEGACY_INACTIVE_STATUSES = {"superseded", "archived"}


def lifecycle_status(entry: dict) -> str:
    """Return the canonical artifact lifecycle status."""
    raw_status = str(entry.get("status", "")).strip().lower()
    if raw_status in CANONICAL_LIFECYCLE_STATUSES:
        return raw_status
    if raw_status in LEGACY_ACTIVE_STATUSES:
        return "active"
    if raw_status in LEGACY_INACTIVE_STATUSES:
        return raw_status

    legacy_quality = str(entry.get("quality_status", "")).strip().lower()
    if legacy_quality in LEGACY_ACTIVE_STATUSES:
        return "active"
    if legacy_quality in LEGACY_INACTIVE_STATUSES:
        return legacy_quality
    return "active"


def is_active_artifact(entry: dict) -> bool:
    return lifecycle_status(entry) == "active"


def normalize_artifact_entry(entry: dict, *, for_write: bool = False) -> dict:
    normalized = dict(entry)
    normalized["status"] = lifecycle_status(normalized)
    if for_write:
        normalized.pop("quality_status", None)
    return normalized
