"""Registry of Wasp UserObjects (.ghuser) installed on this machine.

Scans ``%APPDATA%\\Grasshopper\\UserObjects`` for ``Wasp_*.ghuser`` files.
Registry key = lowercased filename minus ``Wasp_`` prefix and ``.ghuser``
suffix, with spaces/hyphens converted to underscores (PROTOCOL.md).

Example: ``Wasp_Field-driven Aggregation.ghuser`` -> ``field_driven_aggregation``
"""

from __future__ import annotations

import difflib
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

WASP_PREFIX = "wasp_"
GHUSER_SUFFIX = ".ghuser"

# Category guess priority: first keyword hit wins (PROTOCOL.md category set:
# part/connection/rule/aggregation/field/disco/util).
_CATEGORY_RULES: List[tuple[str, str]] = [
    ("disco", "disco"),
    ("field", "field"),
    ("connection", "connection"),
    ("rule", "rule"),
    ("aggregation", "aggregation"),
    ("collider", "part"),
    ("attribute", "part"),
    ("part", "part"),
]


def default_userobjects_dir() -> Path:
    """%APPDATA%\\Grasshopper\\UserObjects (env override WASP_USEROBJECTS_DIR)."""
    override = os.environ.get("WASP_USEROBJECTS_DIR")
    if override:
        return Path(override)
    appdata = os.environ.get("APPDATA")
    if not appdata:
        # Non-Windows fallback (dev/test machines).
        appdata = str(Path.home() / "AppData" / "Roaming")
    return Path(appdata) / "Grasshopper" / "UserObjects"


def key_from_filename(filename: str) -> str:
    """Convert 'Wasp_Basic Part.ghuser' -> 'basic_part'."""
    name = filename.strip().lower()
    if name.endswith(GHUSER_SUFFIX):
        name = name[: -len(GHUSER_SUFFIX)]
    if name.startswith(WASP_PREFIX):
        name = name[len(WASP_PREFIX):]
    return normalize(name)


def normalize(name: str) -> str:
    """Lowercase, spaces/hyphens -> underscores, collapse repeats."""
    name = name.strip().lower()
    name = re.sub(r"[\s\-]+", "_", name)
    name = re.sub(r"_+", "_", name)
    return name.strip("_")


def guess_category(key: str) -> str:
    for keyword, category in _CATEGORY_RULES:
        if keyword in key:
            return category
    return "util"


@dataclass
class WaspComponent:
    key: str
    filename: str
    path: str
    category: str
    # Filled in lazily after the first add_user_object round-trip, if cached.
    inputs: Optional[list] = field(default=None)
    outputs: Optional[list] = field(default=None)

    def to_dict(self) -> Dict:
        out = {
            "key": self.key,
            "filename": self.filename,
            "path": self.path,
            "category": self.category,
        }
        if self.inputs is not None:
            out["inputs"] = self.inputs
        if self.outputs is not None:
            out["outputs"] = self.outputs
        return out


class RegistryLookupError(LookupError):
    """Raised when a name cannot be resolved to a registry entry."""

    def __init__(self, name: str, suggestions: List[str]):
        self.name = name
        self.suggestions = suggestions
        msg = f"No Wasp component matching {name!r}"
        if suggestions:
            msg += f"; closest: {', '.join(suggestions[:5])}"
        super().__init__(msg)


class WaspRegistry:
    """Scans and indexes Wasp .ghuser UserObjects."""

    def __init__(self, directory: Optional[os.PathLike] = None):
        self.directory = Path(directory) if directory else default_userobjects_dir()
        self.entries: Dict[str, WaspComponent] = {}

    def scan(self) -> Dict[str, WaspComponent]:
        """(Re)scan the UserObjects directory. Returns the entry dict."""
        self.entries = {}
        if not self.directory.is_dir():
            return self.entries
        for entry in sorted(self.directory.iterdir()):
            name = entry.name
            if not name.lower().endswith(GHUSER_SUFFIX):
                continue
            if not name.lower().startswith(WASP_PREFIX):
                continue
            key = key_from_filename(name)
            self.entries[key] = WaspComponent(
                key=key,
                filename=name,
                path=str(entry.resolve()),
                category=guess_category(key),
            )
        return self.entries

    def lookup(self, name: str) -> WaspComponent:
        """Resolve a name to a registry entry with fuzzy fallback.

        Resolution order:
          1. exact key match after normalization ('Basic Part' -> basic_part)
          2. unique substring match ('stochastic' -> stochastic_aggregation)
          3. difflib close match
        Raises RegistryLookupError (with suggestions) when nothing matches.
        """
        if not self.entries:
            self.scan()
        query = key_from_filename(name) if name.lower().endswith(GHUSER_SUFFIX) else normalize(
            name[5:] if name.lower().startswith(WASP_PREFIX) else name
        )
        if query in self.entries:
            return self.entries[query]

        # Substring fallback (either direction), shortest key wins.
        substr = [k for k in self.entries if query in k or k in query]
        if substr:
            substr.sort(key=len)
            return self.entries[substr[0]]

        # Token subset fallback: every query token appears in the key.
        tokens = [t for t in query.split("_") if t]
        if tokens:
            token_hits = [k for k in self.entries if all(t in k for t in tokens)]
            if token_hits:
                token_hits.sort(key=len)
                return self.entries[token_hits[0]]

        close = difflib.get_close_matches(query, list(self.entries), n=5, cutoff=0.6)
        if close:
            return self.entries[close[0]]

        suggestions = difflib.get_close_matches(query, list(self.entries), n=5, cutoff=0.3)
        raise RegistryLookupError(name, suggestions)

    def list_entries(self) -> List[Dict]:
        if not self.entries:
            self.scan()
        return [c.to_dict() for c in sorted(self.entries.values(), key=lambda c: c.key)]


# Module-level default registry -------------------------------------------

_default_registry: Optional[WaspRegistry] = None


def get_registry() -> WaspRegistry:
    global _default_registry
    if _default_registry is None:
        _default_registry = WaspRegistry()
        _default_registry.scan()
    return _default_registry


def scan() -> Dict[str, WaspComponent]:
    return get_registry().scan()


def lookup(name: str) -> WaspComponent:
    return get_registry().lookup(name)
