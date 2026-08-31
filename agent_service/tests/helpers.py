from __future__ import annotations

from types import SimpleNamespace
from typing import Any


class FakeAI:
    def __init__(self):
        self.summary_calls: list[dict[str, Any]] = []
        self.image_calls: list[dict[str, Any]] = []

    def summarize(self, messages, **kwargs):
        call = {"messages": list(messages), **kwargs}
        self.summary_calls.append(call)
        texts = [str(item.get("text") or "") for item in messages]
        return {"ok": True, "message": "SUMMARY: " + " | ".join(texts[-3:])}

    def understand_image(self, image_bytes: bytes, **kwargs):
        self.image_calls.append({"size": len(image_bytes), **kwargs})
        return {"ok": True, "message": f"IMAGE:{len(image_bytes)}"}


class FakeCore:
    def __init__(self):
        self.sends = []
        self.media = b"fake-image"

    def ensure_contract(self, expected_major: int = 1):
        return {"ok": True, "service": "fake-core", "contract_version": expected_major}

    def send_text(self, account_id: str, chat_id: str, text: str, **kwargs):
        item = {"account_id": account_id, "chat_id": chat_id, "text": text, **kwargs}
        self.sends.append(item)
        return {"send_id": f"send-{len(self.sends)}", "status": "accepted", **item}

    def get_media(self, account_id: str, media_id: str):
        return SimpleNamespace(status=200, body=self.media, headers={"Content-Type": "image/png"})

