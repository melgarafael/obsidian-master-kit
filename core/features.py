"""Feature helpers compartilhados entre core/scanner.py e Epic 02+.

Importante: word_count, char_count, body_hash ja sao computados por
core.parser.ParsedNote. Este modulo so adiciona helpers que mais de
um consumer reusa (ex: regra de re-embed).
"""

from __future__ import annotations

from core.parser import ParsedNote, parse_markdown  # re-export

__all__ = ["ParsedNote", "parse_markdown", "should_reembed"]


def should_reembed(
    *,
    old_hash: str | None,
    new_hash: str,
    old_word_count: int | None,
    new_word_count: int,
    old_title: str | None,
    new_title: str | None,
    old_body_prefix: str | None,
    new_body_prefix: str | None,
    threshold: float = 0.15,
) -> bool:
    """Gate de re-embed canonica (BRIEF §5.1 e plan da wave 3).

    Re-embed IF body_hash mudou E (word_count delta > threshold OU
    title mudou OU primeiros 500 chars mudaram). Nova nota (old_hash None)
    sempre re-embedda.
    """
    if old_hash is None:
        return True
    if new_hash == old_hash:
        return False
    if old_title != new_title:
        return True
    if old_word_count and abs(new_word_count - old_word_count) / old_word_count > threshold:
        return True
    if old_body_prefix != new_body_prefix:
        return True
    return False
