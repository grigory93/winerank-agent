"""Wine list manifest: load, validate, and generate YAML manifest."""
from pathlib import Path
from typing import Optional

import yaml

from winerank.sft.schemas import Manifest, ManifestEntry


def _infer_restaurant_name(file_path: Path) -> str:
    """Infer a human-readable restaurant name from the filename."""
    stem = file_path.stem
    name = stem.replace("-", " ").replace("_", " ")
    # Capitalize first letter of each word
    words = name.split()
    capitalized = []
    for w in words:
        if w.upper() == w and len(w) > 2:
            capitalized.append(w)
        else:
            capitalized.append(w.capitalize())
    return " ".join(capitalized)


def _make_list_id(file_path: Path, existing_ids: set[str]) -> str:
    """Generate a unique slug-style list ID from the filename."""
    stem = file_path.stem.lower()
    # Replace spaces and special chars with dashes
    slug = ""
    for ch in stem:
        if ch.isalnum():
            slug += ch
        elif ch in (" ", "-", "_"):
            slug += "-"
    # Collapse consecutive dashes
    while "--" in slug:
        slug = slug.replace("--", "-")
    slug = slug.strip("-")
    # Truncate very long slugs
    if len(slug) > 60:
        slug = slug[:60].rstrip("-")
    # Ensure uniqueness
    base = slug
    counter = 1
    while slug in existing_ids:
        slug = f"{base}-{counter}"
        counter += 1
    return slug


def generate_manifest(examples_dir: Path) -> Manifest:
    """
    Scan the examples directory and generate a manifest with all wine lists.

    Args:
        examples_dir: Directory containing PDF and HTML wine list files.

    Returns:
        A Manifest instance with an entry for each discovered file.
    """
    entries = []
    existing_ids: set[str] = set()

    patterns = ["*.pdf", "*.html", "*.htm"]
    files: list[Path] = []
    for pattern in patterns:
        files.extend(sorted(examples_dir.glob(pattern)))

    for file_path in files:
        suffix = file_path.suffix.lower()
        file_type = "pdf" if suffix == ".pdf" else "html"
        list_id = _make_list_id(file_path, existing_ids)
        existing_ids.add(list_id)
        entries.append(
            ManifestEntry(
                list_id=list_id,
                restaurant_name=_infer_restaurant_name(file_path),
                file_path=str(file_path),
                file_type=file_type,
            )
        )

    return Manifest(lists=entries)


def save_manifest(manifest: Manifest, output_path: Path) -> None:
    """Save manifest to YAML file."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "lists": [
            {
                "list_id": e.list_id,
                "restaurant_name": e.restaurant_name,
                "file_path": e.file_path,
                "file_type": e.file_type,
                **({"notes": e.notes} if e.notes else {}),
            }
            for e in manifest.lists
        ]
    }
    with open(output_path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


def load_manifest(manifest_path: Path) -> Manifest:
    """
    Load manifest from YAML file.

    Args:
        manifest_path: Path to manifest.yaml

    Returns:
        Parsed Manifest instance.

    Raises:
        FileNotFoundError: If manifest_path does not exist.
        ValueError: If manifest YAML is invalid.
    """
    if not manifest_path.exists():
        raise FileNotFoundError(
            f"Manifest not found at {manifest_path}. "
            "Run 'winerank sft-data init' to generate it."
        )
    with open(manifest_path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    if not raw or "lists" not in raw:
        raise ValueError(f"Invalid manifest at {manifest_path}: missing 'lists' key")

    entries = []
    for item in raw["lists"]:
        if "list_id" not in item or "file_path" not in item:
            raise ValueError(
                f"Invalid manifest entry (missing list_id or file_path): {item}"
            )
        entries.append(
            ManifestEntry(
                list_id=item["list_id"],
                restaurant_name=item.get("restaurant_name", item["list_id"]),
                file_path=item["file_path"],
                file_type=item.get("file_type", "pdf"),
                notes=item.get("notes"),
            )
        )

    return Manifest(lists=entries)


def get_or_create_manifest(
    manifest_path: Path,
    examples_dir: Optional[Path] = None,
) -> Manifest:
    """
    Load existing manifest or generate a new one from examples_dir.

    Args:
        manifest_path: Path to manifest.yaml
        examples_dir: Directory with wine list files (used if manifest doesn't exist)

    Returns:
        Manifest instance.
    """
    if manifest_path.exists():
        return load_manifest(manifest_path)
    if examples_dir is None:
        raise FileNotFoundError(
            f"Manifest not found at {manifest_path} and no examples_dir provided."
        )
    return generate_manifest(examples_dir)
