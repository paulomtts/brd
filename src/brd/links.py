import re
from collections.abc import Callable
from dataclasses import dataclass

_LINK = re.compile(r"\[\[([^\[\]\n]+?)\]\]")
_INLINE_CODE = re.compile(r"`[^`\n]*`")
_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")


@dataclass(frozen=True)
class LinkToken:
    target: str
    alias: str | None
    start: int
    end: int


def _code_spans(text: str) -> list[tuple[int, int]]:
    """Character ranges covered by fenced code blocks and inline code spans."""
    spans: list[tuple[int, int]] = []
    offset = 0
    fence: str | None = None
    fence_start = 0
    for line in text.splitlines(keepends=True):
        match = _FENCE.match(line)
        if fence is None:
            if match:
                fence = match.group(1)
                fence_start = offset
            else:
                for inline in _INLINE_CODE.finditer(line):
                    spans.append((offset + inline.start(), offset + inline.end()))
        elif match and match.group(1)[0] == fence[0] and len(match.group(1)) >= len(fence):
            spans.append((fence_start, offset + len(line)))
            fence = None
        offset += len(line)
    if fence is not None:
        spans.append((fence_start, len(text)))
    return spans


def _split(inner: str) -> tuple[str, str | None]:
    target, has_alias, alias = inner.partition("|")
    target = target.partition("#")[0].strip()
    alias = alias.strip() if has_alias else ""
    return target, alias or None


def parse(text: str | None) -> list[LinkToken]:
    if not text:
        return []
    spans = _code_spans(text)
    tokens = []
    for match in _LINK.finditer(text):
        if any(start <= match.start() < end for start, end in spans):
            continue
        target, alias = _split(match.group(1))
        if target:
            tokens.append(LinkToken(target, alias, match.start(), match.end()))
    return tokens


def render(text: str | None, display: Callable[[LinkToken], str | None]) -> str:
    """Rewrite each link as [[<alias or target title>]]; unresolved links keep
    their text and gain an '(unresolved)' marker. Links in code are untouched."""
    if not text:
        return ""
    parts = []
    position = 0
    for token in parse(text):
        parts.append(text[position : token.start])
        title = display(token)
        if title is None:
            parts.append(f"[[{token.alias or token.target}]] (unresolved)")
        else:
            parts.append(f"[[{token.alias or title}]]")
        position = token.end
    parts.append(text[position:])
    return "".join(parts)
