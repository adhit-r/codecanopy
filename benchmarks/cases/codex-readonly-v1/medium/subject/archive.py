from pathlib import Path


def write_entry(root: Path, name: str, data: bytes) -> None:
    target = root / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
