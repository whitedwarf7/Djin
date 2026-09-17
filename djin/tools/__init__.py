"""Importing this package registers every Djin tool."""

from djin.tools import (  # noqa: F401  (imported for registration side effects)
    calendar_tools,
    gmail_tools,
    notes_tools,
    reddit_tools,
    search_tools,
)
from djin.tools.registry import (
    REGISTRY,
    Risk,
    ToolError,
    ToolSpec,
    build_preview,
    get_tool,
    requires_approval,
    tool_schemas,
)

__all__ = [
    "REGISTRY",
    "Risk",
    "ToolError",
    "ToolSpec",
    "build_preview",
    "get_tool",
    "requires_approval",
    "tool_schemas",
]
