"""
Prompt-injection defense for uploaded documents.

Primary defense is structural: the parser prompt labels document text as UNTRUSTED
DATA and tells the model never to obey instructions inside it (see parse_assignment).

This module adds a visible heuristic flag so a teacher reviewing the parse can see
that the upload *tried* to inject instructions. It does not block parsing -- it
surfaces the risk for the human approver.
"""

from __future__ import annotations

_SUSPICIOUS = [
    "ignore previous",
    "ignore all previous",
    "ignore the above",
    "disregard previous",
    "disregard the",
    "system prompt",
    "you are now",
    "act as",
    "new instructions",
    "override",
    "do not follow",
    "assistant:",
    "<|im_start|>",
]


def scan_for_injection(text: str) -> list[str]:
    """Return the suspicious phrases found in the document (lowercased match)."""
    low = text.lower()
    return [phrase for phrase in _SUSPICIOUS if phrase in low]
