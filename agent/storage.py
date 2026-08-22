"""Atomic JSON persistence shared by the opportunity and SME state files.

Both data files are read by the dashboard while the agent may be rewriting
them, so every write goes to a sibling temp file and is then renamed:
`os.replace` is atomic on POSIX and Windows, so a reader sees either the old
document or the new one — never a truncated one.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger(__name__)

# mkstemp creates 0600. The mirrored copy is served by the web app and may be
# read by a different user, so widen to the usual 0644.
_FILE_MODE = 0o644


def write_json(path: Path, data: Any) -> None:
    """Atomically write `data` as pretty-printed JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, indent=2, ensure_ascii=False)

    handle, temp_path = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as file:
            file.write(payload)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        os.replace(temp_path, path)
        os.chmod(path, _FILE_MODE)
    except Exception:
        Path(temp_path).unlink(missing_ok=True)
        raise


def read_json(path: Path) -> dict[str, Any] | None:
    """Read a JSON object, or None when it is missing, unreadable or malformed.

    A corrupt state file is recoverable — the next run rebuilds it — so this
    logs and degrades rather than raising.
    """
    if not path.exists():
        LOGGER.info("no state file at %s", path)
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        LOGGER.warning("could not read %s (%s); treating as absent", path, exc)
        return None
    if not isinstance(raw, dict):
        LOGGER.warning("%s did not contain a JSON object; treating as absent", path)
        return None
    return raw
