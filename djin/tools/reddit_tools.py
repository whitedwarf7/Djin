"""Reddit reading tools via the official OAuth API."""

from __future__ import annotations

import re
from typing import Any

from djin.integrations import reddit_auth
from djin.tools.registry import Risk, ToolError, register, wrap_untrusted

SUBREDDIT_RE = re.compile(r"^[A-Za-z0-9_]{2,21}$")
POST_ID_RE = re.compile(r"^[a-z0-9]{4,12}$")
LISTINGS = {"best", "hot", "new", "top", "rising"}
TIME_FILTERS = {"hour", "day", "week", "month", "year", "all"}
MAX_COMMENT_CHARS = 600


def _post_line(data: dict[str, Any]) -> str:
    body = (data.get("selftext") or "").strip().replace("\n", " ")
    if len(body) > 400:
        body = body[:400] + "..."
    line = (
        f"- id={data.get('id')} | r/{data.get('subreddit')} | score={data.get('score')}"
        f" | comments={data.get('num_comments')}\n"
        f"  title: {data.get('title')}\n"
        f"  link: https://www.reddit.com{data.get('permalink', '')}"
    )
    if url := data.get("url_overridden_by_dest"):
        line += f"\n  external: {url}"
    if body:
        line += f"\n  text: {body}"
    return line


@register(
    name="reddit_browse",
    description=(
        "Browse Reddit posts using the user's account."
        " Omit 'subreddit' to read their personalised front page."
    ),
    parameters={
        "type": "object",
        "properties": {
            "subreddit": {"type": "string", "description": "Subreddit name without 'r/'."},
            "listing": {
                "type": "string",
                "enum": sorted(LISTINGS),
                "default": "hot",
            },
            "limit": {"type": "integer", "description": "Posts to return (1-25).", "default": 10},
            "time_filter": {
                "type": "string",
                "enum": sorted(TIME_FILTERS),
                "description": "Only applies when listing is 'top'.",
                "default": "day",
            },
        },
    },
    risk=Risk.READ,
    untrusted_output=True,
    tags=("reddit",),
)
def reddit_browse(
    subreddit: str | None = None,
    listing: str = "hot",
    limit: int = 10,
    time_filter: str = "day",
) -> str:
    if listing not in LISTINGS:
        raise ToolError(f"listing must be one of {sorted(LISTINGS)}.")
    if time_filter not in TIME_FILTERS:
        raise ToolError(f"time_filter must be one of {sorted(TIME_FILTERS)}.")

    params: dict[str, Any] = {"limit": max(1, min(int(limit), 25))}
    if listing == "top":
        params["t"] = time_filter

    if subreddit:
        name = subreddit.removeprefix("r/").strip("/")
        if not SUBREDDIT_RE.match(name):
            raise ToolError(f"'{subreddit}' is not a valid subreddit name.")
        path = f"/r/{name}/{listing}"
        source = f"reddit:r/{name}/{listing}"
    else:
        path = f"/{listing}"
        source = f"reddit:frontpage/{listing}"

    payload = reddit_auth.api_get(path, params)
    children = payload.get("data", {}).get("children", [])
    if not children:
        return f"No posts found for {source}."

    body = "\n".join(_post_line(child.get("data", {})) for child in children)
    return wrap_untrusted(source, body)


@register(
    name="reddit_post_comments",
    description="Read a Reddit post and its top comments by post id (from reddit_browse).",
    parameters={
        "type": "object",
        "properties": {
            "post_id": {"type": "string", "description": "Post id, e.g. '1a2b3c'."},
            "limit": {"type": "integer", "description": "Comments to return (1-30).", "default": 15},
        },
        "required": ["post_id"],
    },
    risk=Risk.READ,
    untrusted_output=True,
    tags=("reddit",),
)
def reddit_post_comments(post_id: str, limit: int = 15) -> str:
    identifier = post_id.removeprefix("t3_").strip()
    if not POST_ID_RE.match(identifier):
        raise ToolError(f"'{post_id}' is not a valid Reddit post id.")

    payload = reddit_auth.api_get(
        f"/comments/{identifier}", {"limit": max(1, min(int(limit), 30)), "depth": 2}
    )
    if not isinstance(payload, list) or len(payload) < 2:
        raise ToolError("Unexpected response from Reddit.")

    post = payload[0].get("data", {}).get("children", [{}])[0].get("data", {})
    lines = [
        f"Post: {post.get('title')}",
        f"Subreddit: r/{post.get('subreddit')} | score={post.get('score')}",
        f"Link: https://www.reddit.com{post.get('permalink', '')}",
    ]
    if selftext := (post.get("selftext") or "").strip():
        lines.append(f"\n{selftext[:2000]}")

    lines.append("\nTop comments:")
    for child in payload[1].get("data", {}).get("children", []):
        data = child.get("data", {})
        text = (data.get("body") or "").strip()
        if not text:
            continue
        if len(text) > MAX_COMMENT_CHARS:
            text = text[:MAX_COMMENT_CHARS] + "..."
        lines.append(f"- u/{data.get('author')} ({data.get('score')}): {text}")

    return wrap_untrusted(f"reddit:post/{identifier}", "\n".join(lines))


@register(
    name="reddit_saved",
    description="List posts the user has saved on Reddit.",
    parameters={
        "type": "object",
        "properties": {
            "limit": {"type": "integer", "description": "Items to return (1-25).", "default": 10},
        },
    },
    risk=Risk.READ,
    untrusted_output=True,
    tags=("reddit",),
)
def reddit_saved(limit: int = 10) -> str:
    user = reddit_auth.username()
    payload = reddit_auth.api_get(
        f"/user/{user}/saved", {"limit": max(1, min(int(limit), 25))}
    )
    children = payload.get("data", {}).get("children", [])
    if not children:
        return "No saved Reddit items found."

    lines = []
    for child in children:
        data = child.get("data", {})
        if child.get("kind") == "t3":
            lines.append(_post_line(data))
        else:
            text = (data.get("body") or "").strip().replace("\n", " ")
            lines.append(
                f"- comment in r/{data.get('subreddit')} by u/{data.get('author')}: {text[:300]}"
            )
    return wrap_untrusted("reddit:saved", "\n".join(lines))
