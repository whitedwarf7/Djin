"""Local Markdown notes. The vault is a plain folder so it can sync to Drive later."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from djin.config import get_settings
from djin.tools.registry import Risk, ToolError, register, wrap_untrusted

SLUG_RE = re.compile(r"[^a-z0-9]+")
MAX_NOTE_CHARS = 60000


def _notes_dir() -> Path:
    settings = get_settings()
    settings.ensure_dirs()
    return settings.notes_dir.resolve()


def _slug(title: str) -> str:
    slug = SLUG_RE.sub("-", title.lower()).strip("-")
    return (slug or "note")[:60]


def _resolve(filename: str) -> Path:
    """Resolve a note path and refuse anything outside the notes folder."""
    root = _notes_dir()
    name = Path(filename).name
    if not name.endswith(".md"):
        name += ".md"
    path = (root / name).resolve()
    if path.parent != root:
        raise ToolError("Notes must live directly inside the notes folder.")
    return path


def _create_preview(
    title: str, content: str, tags: list[str] | None = None, sources: list[str] | None = None
) -> str:
    excerpt = content if len(content) <= 600 else content[:600] + "..."
    lines = [f"Create note: {title}"]
    if tags:
        lines.append(f"Tags: {', '.join(tags)}")
    if sources:
        lines.append(f"Sources: {', '.join(sources)}")
    lines.append(f"\n{excerpt}")
    return "\n".join(lines)


@register(
    name="notes_create",
    description=(
        "Create a Markdown note in the user's local notes vault."
        " Always include the source URLs when the note summarises web content."
    ),
    parameters={
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "content": {"type": "string", "description": "Markdown body of the note."},
            "tags": {"type": "array", "items": {"type": "string"}},
            "sources": {
                "type": "array",
                "items": {"type": "string"},
                "description": "URLs the note is based on.",
            },
        },
        "required": ["title", "content"],
    },
    risk=Risk.WRITE,
    preview=_create_preview,
    tags=("notes",),
)
def notes_create(
    title: str, content: str, tags: list[str] | None = None, sources: list[str] | None = None
) -> str:
    if len(content) > MAX_NOTE_CHARS:
        raise ToolError("Note content is too large.")

    root = _notes_dir()
    stem = f"{datetime.now():%Y-%m-%d}-{_slug(title)}"
    path = root / f"{stem}.md"
    counter = 2
    while path.exists():
        path = root / f"{stem}-{counter}.md"
        counter += 1

    front = [
        "---",
        f"title: {title}",
        f"created: {datetime.now().isoformat(timespec='seconds')}",
        f"tags: [{', '.join(tags or [])}]",
    ]
    if sources:
        front.append("sources:")
        front.extend(f"  - {src}" for src in sources)
    front.append("---")

    path.write_text("\n".join(front) + f"\n\n# {title}\n\n{content}\n", encoding="utf-8")
    return f"Saved note '{path.name}' in {root}."


def _append_preview(filename: str, content: str) -> str:
    excerpt = content if len(content) <= 400 else content[:400] + "..."
    return f"Append to note: {filename}\n\n{excerpt}"


@register(
    name="notes_append",
    description="Append a Markdown section to an existing note.",
    parameters={
        "type": "object",
        "properties": {
            "filename": {"type": "string", "description": "Note file name, e.g. '2026-09-17-ai.md'."},
            "content": {"type": "string"},
        },
        "required": ["filename", "content"],
    },
    risk=Risk.WRITE,
    preview=_append_preview,
    tags=("notes",),
)
def notes_append(filename: str, content: str) -> str:
    path = _resolve(filename)
    if not path.exists():
        raise ToolError(f"Note '{path.name}' does not exist. Use notes_create instead.")
    stamp = datetime.now().isoformat(timespec="minutes")
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"\n\n---\n_Added {stamp}_\n\n{content}\n")
    return f"Appended to '{path.name}'."


@register(
    name="notes_list",
    description="List the most recently modified notes in the vault.",
    parameters={
        "type": "object",
        "properties": {"limit": {"type": "integer", "default": 20}},
    },
    risk=Risk.READ,
    tags=("notes",),
)
def notes_list(limit: int = 20) -> str:
    root = _notes_dir()
    files = sorted(root.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    files = files[: max(1, min(int(limit), 100))]
    if not files:
        return "The notes vault is empty."
    return "\n".join(
        f"- {path.name} (modified {datetime.fromtimestamp(path.stat().st_mtime):%Y-%m-%d %H:%M})"
        for path in files
    )


@register(
    name="notes_search",
    description="Full-text search across the local notes vault.",
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "limit": {"type": "integer", "default": 5},
        },
        "required": ["query"],
    },
    risk=Risk.READ,
    untrusted_output=True,
    tags=("notes",),
)
def notes_search(query: str, limit: int = 5) -> str:
    needle = query.lower().strip()
    if not needle:
        raise ToolError("Search query is empty.")

    matches: list[str] = []
    for path in sorted(_notes_dir().glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True):
        text = path.read_text(encoding="utf-8", errors="replace")
        if needle not in text.lower():
            continue
        index = text.lower().index(needle)
        excerpt = text[max(0, index - 200) : index + 400].replace("\n", " ")
        matches.append(f"- {path.name}: ...{excerpt}...")
        if len(matches) >= max(1, min(int(limit), 20)):
            break

    if not matches:
        return f"No notes matched '{query}'."
    return wrap_untrusted("notes", "\n".join(matches))
