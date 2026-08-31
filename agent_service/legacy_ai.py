from __future__ import annotations

import importlib.util
import json
import mimetypes
import sys
import tempfile
import threading
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BUILTIN_SKILLS_DIR = ROOT / "agent_console" / "builtin_skills"
LEGACY_CONSOLE_APP = ROOT / "agent_console" / "app.py"


_MODULE = None
_MODULE_LOCK = threading.Lock()


def _frontmatter(text: str) -> dict[str, str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    output: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        key, sep, value = line.partition(":")
        if sep:
            output[key.strip()] = value.strip()
    return output


def builtin_skills() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    if not BUILTIN_SKILLS_DIR.exists():
        return items
    for path in sorted(BUILTIN_SKILLS_DIR.glob("*/SKILL.md")):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        meta = _frontmatter(text)
        items.append(
            {
                "skill_id": str(meta.get("name") or path.parent.name),
                "name": str(meta.get("name") or path.parent.name),
                "description": str(meta.get("description") or ""),
                "source": str(path.relative_to(ROOT)).replace("\\", "/"),
                "body": text,
            }
        )
    return items


def load_legacy_console():
    """Load the audited Console AI implementation lazily for reuse.

    Loading is deferred so Core-only/records-only deployments do not pay the
    import cost or require an LLM configuration until an AI action is invoked.
    """

    global _MODULE
    if _MODULE is not None:
        return _MODULE
    with _MODULE_LOCK:
        if _MODULE is not None:
            return _MODULE
        if not LEGACY_CONSOLE_APP.exists():
            raise RuntimeError(f"legacy AI implementation not found: {LEGACY_CONSOLE_APP}")
        module_name = "wechat_agent_reused_console_app"
        spec = importlib.util.spec_from_file_location(module_name, LEGACY_CONSOLE_APP)
        if spec is None or spec.loader is None:
            raise RuntimeError("unable to load legacy Console AI module")
        module = importlib.util.module_from_spec(spec)
        # app.py imports helper modules from its own directory in the upstream
        # monolith. Preserve that import environment without copying functions.
        console_dir = str(LEGACY_CONSOLE_APP.parent)
        if console_dir not in sys.path:
            sys.path.insert(0, console_dir)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        _MODULE = module
        return module


class LegacyAIAdapter:
    """Adapter over existing model, vision and Agent personality code."""

    def skills(self) -> list[dict[str, Any]]:
        return builtin_skills()

    def summarize(
        self,
        messages: list[dict[str, Any]],
        *,
        instruction: str = "",
        account_id: str = "",
        chat_id: str = "",
    ) -> dict[str, Any]:
        if not messages:
            return {"ok": False, "error": "no messages to summarize"}
        legacy = load_legacy_console()
        config = legacy.read_config()
        profile = {**legacy.active_profile(config)}
        profile["max_tokens"] = max(int(profile.get("max_tokens") or 512), 900)
        profile["temperature"] = min(float(profile.get("temperature") or 0.4), 0.45)
        transcript = []
        for item in messages[-100:]:
            speaker = item.get("author_name") or item.get("author_id") or (
                "我" if item.get("direction") == "outgoing" else "未知成员"
            )
            transcript.append(f"{item.get('created_at') or ''} {speaker}: {item.get('text') or ''}")
        prompt = (
            "请总结下面的微信群聊天记录。保留关键事实、结论、待办、分歧和未解决问题；"
            "不要编造记录中没有的信息。\n"
            f"account_id={account_id}\nchat_id={chat_id}\n"
        )
        if instruction.strip():
            prompt += f"额外要求：{instruction.strip()}\n"
        prompt += "\n聊天记录：\n" + "\n".join(transcript)
        result = legacy.request_llm(profile, prompt, legacy.build_agent_system_prompt(config))
        if not isinstance(result, dict):
            return {"ok": False, "error": "legacy request_llm returned invalid result"}
        return result

    def understand_image(
        self,
        image_bytes: bytes,
        *,
        filename: str = "image.jpg",
        message: dict[str, Any] | None = None,
        instruction: str = "",
    ) -> dict[str, Any]:
        if not image_bytes:
            return {"ok": False, "error": "empty image"}
        legacy = load_legacy_console()
        config = legacy.read_config()
        skills = config.get("skills") if isinstance(config.get("skills"), dict) else {}
        settings = skills.get("image_understanding") if isinstance(skills.get("image_understanding"), dict) else {}
        if hasattr(legacy, "image_skill_profile"):
            profile = legacy.image_skill_profile(config, settings)
        else:
            profile = {**legacy.active_profile(config)}
        suffix = Path(filename or "image.jpg").suffix
        if not suffix:
            mime = str((message or {}).get("mime_type") or "")
            suffix = mimetypes.guess_extension(mime) or ".jpg"
        base_prompt = str(settings.get("prompt") or "请理解这张微信群图片的真实内容，并提取关键文字与信息。")
        context = message or {}
        prompt = base_prompt
        if context:
            prompt += (
                "\n\n消息上下文："
                + json.dumps(
                    {
                        "account_id": context.get("account_id"),
                        "chat_id": context.get("chat_id"),
                        "message_id": context.get("message_id"),
                        "author": context.get("author"),
                        "created_at": context.get("created_at"),
                    },
                    ensure_ascii=False,
                )
            )
        if instruction.strip():
            prompt += f"\n额外要求：{instruction.strip()}"
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(prefix="wechat-agent-image-", suffix=suffix, delete=False) as handle:
                handle.write(image_bytes)
                temp_path = Path(handle.name)
            return legacy.request_vision_llm(
                profile,
                prompt,
                temp_path,
                "你是微信群图片理解助手。必须基于真实图片内容回答，不能根据文件名猜测。",
            )
        finally:
            if temp_path is not None:
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError:
                    pass

