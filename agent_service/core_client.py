from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


class CoreApiError(RuntimeError):
    def __init__(self, status: int, code: str, message: str, details: dict[str, Any] | None = None):
        super().__init__(f"Core API {status} {code}: {message}")
        self.status = int(status)
        self.code = str(code)
        self.message = str(message)
        self.details = details or {}


@dataclass(slots=True)
class CoreResponse:
    status: int
    body: Any
    headers: dict[str, str]


class CoreClient:
    """Small stdlib client for the frozen WeChat Core V1 contract."""

    def __init__(self, base_url: str, timeout: float = 20.0):
        self.base_url = str(base_url or "").rstrip("/")
        if not self.base_url.startswith(("http://", "https://")):
            raise ValueError("core base_url must use http:// or https://")
        self.timeout = max(1.0, float(timeout))

    def _request(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, Any] | None = None,
        payload: Any | None = None,
        headers: dict[str, str] | None = None,
        expect_bytes: bool = False,
    ) -> CoreResponse:
        url = f"{self.base_url}{path}"
        if query:
            encoded = urlencode({key: value for key, value in query.items() if value not in (None, "")})
            if encoded:
                url = f"{url}?{encoded}"
        body = None
        request_headers = {"Accept": "application/json"}
        if headers:
            request_headers.update(headers)
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            request_headers.setdefault("Content-Type", "application/json")
        request = Request(url, data=body, headers=request_headers, method=method.upper())
        try:
            with urlopen(request, timeout=self.timeout) as response:
                raw = response.read()
                response_headers = {key: value for key, value in response.headers.items()}
                if expect_bytes:
                    decoded: Any = raw
                else:
                    decoded = json.loads(raw.decode("utf-8") or "{}")
                return CoreResponse(int(response.status), decoded, response_headers)
        except HTTPError as exc:
            raw = exc.read()
            try:
                data = json.loads(raw.decode("utf-8") or "{}")
            except (UnicodeDecodeError, json.JSONDecodeError):
                data = {}
            error = data.get("error") if isinstance(data, dict) else None
            if isinstance(error, dict):
                raise CoreApiError(
                    exc.code,
                    str(error.get("code") or "http_error"),
                    str(error.get("message") or exc.reason),
                    error.get("details") if isinstance(error.get("details"), dict) else {},
                ) from exc
            raise CoreApiError(exc.code, "http_error", str(exc.reason), {}) from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise CoreApiError(0, "core_unavailable", str(exc), {}) from exc
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CoreApiError(0, "invalid_core_response", str(exc), {}) from exc

    def health(self) -> dict[str, Any]:
        return dict(self._request("GET", "/health").body)

    def ensure_contract(self, expected_major: int = 1) -> dict[str, Any]:
        health = self.health()
        version = health.get("contract_version")
        if version != expected_major:
            raise CoreApiError(
                0,
                "unsupported_contract",
                f"wechat-agent requires Core contract_version {expected_major}, got {version!r}",
                {"expected": expected_major, "actual": version},
            )
        return health

    def list_accounts(self) -> list[dict[str, Any]]:
        body = self._request("GET", "/v1/accounts").body
        return list(body.get("accounts") or [])

    def list_chats(self, account_id: str, *, query: str = "", limit: int = 100) -> dict[str, Any]:
        return dict(
            self._request(
                "GET",
                f"/v1/accounts/{quote(account_id, safe='')}/chats",
                query={"query": query, "limit": max(1, min(int(limit), 200))},
            ).body
        )

    def poll_events(
        self,
        *,
        after: str = "0",
        limit: int = 50,
        account_id: str = "",
        consumer_id: str = "wechat-agent",
        timeout: int = 0,
    ) -> dict[str, Any]:
        return dict(
            self._request(
                "GET",
                "/v1/events/poll",
                query={
                    "after": after or "0",
                    "limit": max(1, min(int(limit), 200)),
                    "account_id": account_id,
                    "consumer_id": consumer_id,
                    "timeout": max(0, min(int(timeout), 30)),
                },
            ).body
        )

    def ack_events(self, consumer_id: str, event_ids: list[str]) -> dict[str, Any]:
        if not event_ids:
            return {"consumer_id": consumer_id, "acked_event_ids": [], "acked_count": 0}
        return dict(
            self._request(
                "POST",
                "/v1/events/ack",
                payload={"consumer_id": consumer_id, "event_ids": event_ids},
            ).body
        )

    def get_media(self, account_id: str, media_id: str) -> CoreResponse:
        return self._request(
            "GET",
            f"/v1/media/{quote(media_id, safe='')}",
            query={"account_id": account_id},
            expect_bytes=True,
            headers={"Accept": "*/*"},
        )

    def send_text(
        self,
        account_id: str,
        chat_id: str,
        text: str,
        *,
        target_message_id: str = "",
        mention_member_ids: list[str] | None = None,
        client_request_id: str = "",
        idempotency_key: str = "",
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"account_id": account_id, "chat_id": chat_id, "text": text}
        if target_message_id:
            payload["target_message_id"] = target_message_id
        if mention_member_ids:
            payload["mention_member_ids"] = list(mention_member_ids)
        if client_request_id:
            payload["client_request_id"] = client_request_id
        headers = {"Idempotency-Key": idempotency_key} if idempotency_key else None
        return dict(self._request("POST", "/v1/send/text", payload=payload, headers=headers).body)

