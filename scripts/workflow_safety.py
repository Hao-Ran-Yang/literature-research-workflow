import json
import csv
import tempfile
from pathlib import Path


def require_write_permission(args, operation: str) -> None:
    if not getattr(args, "allow_write", False):
        raise PermissionError(f"{operation} requires explicit --allow-write")


def require_network_permission(args, operation: str) -> None:
    if not getattr(args, "allow_network", False):
        raise PermissionError(f"{operation} requires explicit --allow-network")


def atomic_write_text(path: Path, text: str, encoding: str = "utf-8") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding=encoding, newline="", delete=False, dir=path.parent, prefix=path.name + ".", suffix=".tmp") as handle:
        handle.write(text)
        temp_path = Path(handle.name)
    temp_path.replace(path)


def atomic_write_json(path: Path, data: object) -> None:
    atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def atomic_write_csv(path: Path, fieldnames: list[str], rows: list[dict], encoding: str = "utf-8-sig") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding=encoding, newline="", delete=False, dir=path.parent, prefix=path.name + ".", suffix=".tmp") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
        temp_path = Path(handle.name)
    temp_path.replace(path)
