"""A minimal, uniform DOM API over Scrapling with a BeautifulSoup fallback.

Scrapling's `Selector` gives adaptive, self-healing selectors and is the
preferred backend. It is an optional import: when Scrapling (or its lxml
dependency) is unavailable, we transparently fall back to BeautifulSoup so the
pipeline still runs.

The scraper only ever needs three operations — query by CSS, read text, read an
attribute — so this wrapper exposes exactly those and nothing more.
"""

from __future__ import annotations

from typing import Iterator, Protocol, runtime_checkable

try:  # preferred backend
    from scrapling import Selector as _ScraplingSelector

    HAS_SCRAPLING = True
except Exception:  # pragma: no cover - exercised only without scrapling
    _ScraplingSelector = None  # type: ignore[assignment]
    HAS_SCRAPLING = False

try:
    from bs4 import BeautifulSoup as _BeautifulSoup

    HAS_BS4 = True
except Exception:  # pragma: no cover - exercised only without bs4
    _BeautifulSoup = None  # type: ignore[assignment]
    HAS_BS4 = False


@runtime_checkable
class Node(Protocol):
    """The DOM surface the scrapers depend on."""

    def css(self, selector: str) -> list["Node"]:
        """All descendants matching a CSS selector."""

    def css_first(self, selector: str) -> "Node | None":
        """First descendant matching a CSS selector, or None."""

    def text(self, strip: bool = True) -> str:
        """Concatenated text content of this node and its descendants."""

    def attr(self, name: str, default: str = "") -> str:
        """Attribute value, or `default` when absent."""

    def html(self) -> str:
        """Outer HTML of this node."""


class ScraplingNode:
    """Adapter around a `scrapling.Selector`."""

    __slots__ = ("_node",)

    def __init__(self, node) -> None:
        self._node = node

    def css(self, selector: str) -> list[Node]:
        try:
            return [ScraplingNode(n) for n in self._node.css(selector)]
        except Exception:
            return []

    def css_first(self, selector: str) -> Node | None:
        matches = self.css(selector)
        return matches[0] if matches else None

    def text(self, strip: bool = True) -> str:
        try:
            value = self._node.get_all_text(strip=strip)
        except Exception:
            try:
                value = str(self._node.text)
            except Exception:
                return ""
        return _collapse(value) if strip else str(value)

    def attr(self, name: str, default: str = "") -> str:
        try:
            value = self._node.attrib.get(name)
        except Exception:
            return default
        return str(value) if value is not None else default

    def html(self) -> str:
        try:
            return str(self._node.html_content)
        except Exception:
            return str(self._node)


class SoupNode:
    """Adapter around a BeautifulSoup tag."""

    __slots__ = ("_node",)

    def __init__(self, node) -> None:
        self._node = node

    def css(self, selector: str) -> list[Node]:
        try:
            return [SoupNode(n) for n in self._node.select(selector)]
        except Exception:
            return []

    def css_first(self, selector: str) -> Node | None:
        try:
            found = self._node.select_one(selector)
        except Exception:
            return None
        return SoupNode(found) if found is not None else None

    def text(self, strip: bool = True) -> str:
        value = self._node.get_text(" ", strip=strip)
        return _collapse(value) if strip else value

    def attr(self, name: str, default: str = "") -> str:
        value = self._node.get(name)
        if value is None:
            return default
        if isinstance(value, (list, tuple)):
            return " ".join(str(v) for v in value)
        return str(value)

    def html(self) -> str:
        return str(self._node)


def _collapse(value: str) -> str:
    """Collapse all runs of whitespace (including NBSP) into single spaces."""
    return " ".join(str(value).replace("\xa0", " ").split())


def parse(markup: str, prefer_scrapling: bool = True) -> Node:
    """Parse an HTML document into a `Node`.

    Raises RuntimeError only if neither backend is installed, which means the
    dependencies in requirements.txt were not installed at all.
    """
    if prefer_scrapling and HAS_SCRAPLING:
        try:
            return ScraplingNode(_ScraplingSelector(markup))
        except Exception:
            pass  # fall through to BeautifulSoup
    if HAS_BS4:
        for parser in ("lxml", "html.parser"):
            try:
                return SoupNode(_BeautifulSoup(markup, parser))
            except Exception:
                continue
    raise RuntimeError(
        "No HTML backend available. Install requirements.txt (scrapling or beautifulsoup4)."
    )


def backend_name(node: Node) -> str:
    """Which backend produced this node — surfaced in run logs."""
    return "scrapling" if isinstance(node, ScraplingNode) else "beautifulsoup"


def iter_text(nodes: list[Node]) -> Iterator[str]:
    """Text of each node, skipping empties."""
    for node in nodes:
        value = node.text()
        if value:
            yield value
