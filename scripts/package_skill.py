import argparse
import zipfile
from pathlib import Path, PurePosixPath


REQUIRED = ("SKILL.md", "scripts", "schemas", "docs", "templates", "tests")
EXCLUDED_DIRS = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".git"}
EXCLUDED_NAMES = {".DS_Store", "Thumbs.db"}
EXCLUDED_SUFFIXES = {".pyc", ".pyo", ".tmp", ".temp", ".bak", ".swp"}


def include_file(path: Path, root: Path, output: Path) -> bool:
    if path.resolve() == output.resolve():
        return False
    rel = path.relative_to(root)
    return not (
        any(part in EXCLUDED_DIRS for part in rel.parts)
        or path.name in EXCLUDED_NAMES
        or path.name.endswith("~")
        or path.suffix.lower() in EXCLUDED_SUFFIXES
    )


def build_skill_zip(root: Path, output: Path) -> Path:
    root = root.resolve()
    output = output.resolve()
    missing = [name for name in REQUIRED if not (root / name).exists()]
    if missing:
        raise FileNotFoundError("missing required skill files: " + ", ".join(missing))
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
            if path.is_file() and include_file(path, root, output):
                archive.write(path, PurePosixPath(*path.relative_to(root).parts).as_posix())
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a clean literature-research-workflow skill zip.")
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    print(build_skill_zip(Path(args.root), Path(args.output)))


if __name__ == "__main__":
    main()
