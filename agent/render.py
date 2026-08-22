"""Message bodies for notifications.

Kept separate from dispatch so the wording can be unit-tested without any
network or credentials. Each renderer respects the length limit of its channel.
"""

from __future__ import annotations

from html import escape
from typing import Sequence

from .models import ChangeEvent

TELEGRAM_LIMIT = 4096
DISCORD_LIMIT = 2000
_MAX_ITEMS = 12

_KIND_LABELS = {
    "status_change": "Status change",
    "new_high_match": "New strong match",
    "new_opportunity": "Newly listed",
    "deadline_soon": "Deadline approaching",
}
_KIND_EMOJI = {
    "status_change": "🔄",
    "new_high_match": "🎯",
    "new_opportunity": "🆕",
    "deadline_soon": "⏳",
}


def subject(events: Sequence[ChangeEvent]) -> str:
    """Email subject line summarising the run."""
    if not events:
        return "ESA Scout — no changes"

    opened = [
        e for e in events if e.kind == "status_change" and e.opportunity.status == "Open"
    ]
    high = [e for e in events if e.kind == "new_high_match"]

    if opened:
        first = opened[0].opportunity.title
        if len(opened) == 1:
            return f"ESA Scout — {first} is now OPEN"
        return f"ESA Scout — {len(opened)} opportunities now OPEN"
    if high:
        first = high[0].opportunity
        if len(high) == 1:
            return f"ESA Scout — new {first.match_score}% match: {first.title}"
        return f"ESA Scout — {len(high)} new strong matches"
    return f"ESA Scout — {len(events)} update(s)"


def _line(event: ChangeEvent) -> str:
    opportunity = event.opportunity
    label = _KIND_LABELS.get(event.kind, event.kind)
    score = f"{opportunity.match_score}%" if opportunity.match_score else "unscored"
    parts = [f"[{label}] {opportunity.title}", f"  Status: {opportunity.status}"]
    if event.previous_status:
        parts[-1] += f" (was {event.previous_status})"
    parts.append(f"  Match: {score}")
    if opportunity.deadline_text or opportunity.deadline:
        parts.append(f"  Deadline: {opportunity.deadline_text or opportunity.deadline}")
    if opportunity.url:
        parts.append(f"  {opportunity.url}")
    return "\n".join(parts)


def text_body(events: Sequence[ChangeEvent], dashboard_url: str | None = None) -> str:
    """Plain-text body, used for email fallback and as the SMTP alternative."""
    if not events:
        return "No changes detected."
    blocks = [_line(event) for event in events[:_MAX_ITEMS]]
    body = "\n\n".join(blocks)
    if len(events) > _MAX_ITEMS:
        body += f"\n\n… and {len(events) - _MAX_ITEMS} more."
    if dashboard_url:
        body += f"\n\nFull dashboard: {dashboard_url}"
    return body


def html_body(events: Sequence[ChangeEvent], dashboard_url: str | None = None) -> str:
    """HTML email body. Inline styles only — email clients strip <style>."""
    if not events:
        return "<p>No changes detected.</p>"

    cards: list[str] = []
    for event in events[:_MAX_ITEMS]:
        opportunity = event.opportunity
        colour = {"Open": "#16a34a", "Pending": "#ca8a04", "Closed": "#64748b"}.get(
            opportunity.status, "#64748b"
        )
        rows = [
            f'<div style="font-size:12px;text-transform:uppercase;letter-spacing:.06em;'
            f'color:#64748b;margin-bottom:6px">'
            f"{_KIND_EMOJI.get(event.kind, '•')} {escape(_KIND_LABELS.get(event.kind, event.kind))}</div>",
            f'<div style="font-size:17px;font-weight:600;color:#0f172a;margin-bottom:8px">'
            f"{escape(opportunity.title)}</div>",
            f'<span style="display:inline-block;padding:2px 10px;border-radius:999px;'
            f'background:{colour};color:#fff;font-size:12px;font-weight:600">'
            f"{escape(opportunity.status)}</span>",
        ]
        if event.previous_status:
            rows.append(
                f'<span style="color:#64748b;font-size:13px;margin-left:8px">'
                f"was {escape(event.previous_status)}</span>"
            )
        if opportunity.match_score:
            rows.append(
                f'<span style="color:#0f172a;font-size:13px;margin-left:8px">'
                f"Match <strong>{opportunity.match_score}%</strong></span>"
            )
        if opportunity.deadline_text or opportunity.deadline:
            rows.append(
                f'<div style="margin-top:10px;color:#475569;font-size:14px">'
                f"Deadline: {escape(opportunity.deadline_text or opportunity.deadline)}</div>"
            )
        if opportunity.evaluation and opportunity.evaluation.justification:
            rows.append(
                f'<div style="margin-top:10px;color:#334155;font-size:14px;'
                f'line-height:1.5">{escape(opportunity.evaluation.justification)}</div>'
            )
        if opportunity.url:
            rows.append(
                f'<div style="margin-top:14px"><a href="{escape(opportunity.url)}" '
                f'style="color:#2563eb;font-weight:600;text-decoration:none">'
                f"View opportunity →</a></div>"
            )
        cards.append(
            '<div style="border:1px solid #e2e8f0;border-radius:12px;padding:18px;'
            'margin-bottom:14px;background:#ffffff">' + "".join(rows) + "</div>"
        )

    footer = ""
    if len(events) > _MAX_ITEMS:
        footer += (
            f'<p style="color:#64748b;font-size:14px">… and '
            f"{len(events) - _MAX_ITEMS} more.</p>"
        )
    if dashboard_url:
        footer += (
            f'<p style="margin-top:18px"><a href="{escape(dashboard_url)}" '
            f'style="display:inline-block;background:#0f172a;color:#fff;padding:11px 20px;'
            f'border-radius:8px;text-decoration:none;font-weight:600">'
            f"Open ESA Scout dashboard</a></p>"
        )

    return (
        '<div style="font-family:-apple-system,BlinkMacSystemFont,\'Segoe UI\','
        'Roboto,sans-serif;background:#f8fafc;padding:24px">'
        '<div style="max-width:640px;margin:0 auto">'
        '<h1 style="font-size:20px;color:#0f172a;margin:0 0 4px">ESA Scout</h1>'
        '<p style="color:#64748b;font-size:14px;margin:0 0 20px">'
        f"{len(events)} update(s) detected.</p>"
        + "".join(cards)
        + footer
        + "</div></div>"
    )


def telegram_body(events: Sequence[ChangeEvent], dashboard_url: str | None = None) -> str:
    """Telegram message using its HTML parse mode, truncated to the API limit."""
    if not events:
        return "ESA Scout: no changes detected."

    lines = ["<b>ESA Scout</b>", ""]
    for event in events[:_MAX_ITEMS]:
        opportunity = event.opportunity
        emoji = _KIND_EMOJI.get(event.kind, "•")
        title = escape(opportunity.title)
        if opportunity.url:
            title = f'<a href="{escape(opportunity.url)}">{title}</a>'
        lines.append(f"{emoji} <b>{title}</b>")
        detail = f"   {escape(opportunity.status)}"
        if event.previous_status:
            detail += f" (was {escape(event.previous_status)})"
        if opportunity.match_score:
            detail += f" · match {opportunity.match_score}%"
        lines.append(detail)
        if opportunity.deadline_text or opportunity.deadline:
            lines.append(
                f"   Deadline: {escape(opportunity.deadline_text or opportunity.deadline)}"
            )
        lines.append("")

    if len(events) > _MAX_ITEMS:
        lines.append(f"… and {len(events) - _MAX_ITEMS} more.")
    if dashboard_url:
        lines.append(f'<a href="{escape(dashboard_url)}">Open dashboard</a>')

    return _truncate("\n".join(lines), TELEGRAM_LIMIT)


def discord_body(events: Sequence[ChangeEvent], dashboard_url: str | None = None) -> str:
    """Discord webhook content using Markdown, truncated to the API limit."""
    if not events:
        return "**ESA Scout**: no changes detected."

    lines = ["**ESA Scout**", ""]
    for event in events[:_MAX_ITEMS]:
        opportunity = event.opportunity
        emoji = _KIND_EMOJI.get(event.kind, "•")
        headline = f"{emoji} **{opportunity.title}**"
        if opportunity.url:
            headline += f" — <{opportunity.url}>"
        lines.append(headline)
        detail = f"   {opportunity.status}"
        if event.previous_status:
            detail += f" (was {event.previous_status})"
        if opportunity.match_score:
            detail += f" · match {opportunity.match_score}%"
        if opportunity.deadline_text or opportunity.deadline:
            detail += f" · deadline {opportunity.deadline_text or opportunity.deadline}"
        lines.append(detail)

    if len(events) > _MAX_ITEMS:
        lines.append(f"… and {len(events) - _MAX_ITEMS} more.")
    if dashboard_url:
        lines.append(f"<{dashboard_url}>")

    return _truncate("\n".join(lines), DISCORD_LIMIT)


def _truncate(text: str, limit: int) -> str:
    """Cut to `limit` characters on a line boundary where possible."""
    if len(text) <= limit:
        return text
    marker = "\n…"
    cut = text[: limit - len(marker)]
    boundary = cut.rfind("\n")
    if boundary > limit // 2:
        cut = cut[:boundary]
    return cut + marker
