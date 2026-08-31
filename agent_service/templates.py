from __future__ import annotations

import re
from typing import Any


TOKEN_RE = re.compile(r"{{\s*([A-Za-z0-9_.-]+)\s*}}")


def resolve_path(context: dict[str, Any], path: str) -> Any:
    value: Any = context
    for part in str(path or "").split("."):
        if not part:
            return ""
        if isinstance(value, dict):
            value = value.get(part, "")
        else:
            return ""
    return value


def render_template(body: str, context: dict[str, Any]) -> str:
    """Render a deliberately small, non-executable {{ dotted.path }} template."""

    def replace(match: re.Match[str]) -> str:
        value = resolve_path(context, match.group(1))
        if value is None:
            return ""
        if isinstance(value, (dict, list, tuple)):
            import json

            return json.dumps(value, ensure_ascii=False)
        return str(value)

    return TOKEN_RE.sub(replace, str(body or ""))

