#!/usr/bin/env python3
"""Generate a WeChat group daily report as HTML/PNG."""

from __future__ import annotations

import argparse
import html
import io
import json
import math
import os
import re
import sqlite3
import subprocess
import tempfile
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

ROOT = Path(os.environ.get("WECHATAGENT_ROOT") or Path(__file__).resolve().parents[1])
import sys

sys.path.insert(0, str(ROOT / "memory"))
try:
    from message_parse import message_index_text
except ModuleNotFoundError:
    def message_index_text(row: dict) -> tuple[str, str]:
        raise RuntimeError("message_parse is required when loading WeChat messages")

try:
    DISPLAY_TZ = ZoneInfo("Asia/Shanghai")
except ZoneInfoNotFoundError:
    DISPLAY_TZ = timezone(timedelta(hours=8), "Asia/Shanghai")

RUNTIME_ROOT = Path(os.environ.get("WECHATAGENT_RUNTIME_ROOT") or (ROOT / "runtime"))
DECRYPTED_ROOT = Path(os.environ.get("WECHATAGENT_DECRYPTED_ROOT") or (RUNTIME_ROOT / "wechat-decrypt/decrypted"))
MEMORY_DB = Path(os.environ.get("WECHATAGENT_MEMORY_DB") or (RUNTIME_ROOT / "memory/wechat_memory.sqlite"))
CONTACT_DB = Path(os.environ.get("WECHATAGENT_CONTACT_DB") or (DECRYPTED_ROOT / "contact/contact.db"))
HEAD_IMAGE_DB = Path(os.environ.get("WECHATAGENT_HEAD_IMAGE_DB") or (DECRYPTED_ROOT / "head_image/head_image.db"))
REPORT_DIR = Path(os.environ.get("WECHATAGENT_REPORT_DIR") or (RUNTIME_ROOT / "reports"))

STOPWORDS = {
    "这个",
    "那个",
    "今天",
    "现在",
    "还是",
    "就是",
    "不是",
    "没有",
    "可以",
    "一下",
    "什么",
    "怎么",
    "为啥",
    "为什么",
    "需要",
    "感觉",
    "应该",
    "知道",
    "看看",
    "哈哈",
    "呲牙",
    "捂脸",
    "吃瓜",
    "消息",
    "群里",
    "总结",
    "引用",
    "当前微信",
    "微信版本",
    "支持展示",
    "发起",
    "转账",
    "wxid",
    "http",
    "https",
    "com",
    "www",
    "xml",
    "sysmsg",
    "revokemsg",
    "content",
    "revoketime",
    "想看",
    "大佬",
    "哈哈哈",
    "合十",
    "让我看看",
}

TOPIC_HINTS = [
    "社会社会",
    "小风二代",
    "哥你也需要啊",
    "京豆",
    "青龙",
    "白虎",
    "docker",
    "解密",
    "微信",
    "端口",
    "反代",
    "公网",
    "内网",
    "牙龈",
    "GitHub",
    "自动化",
]

TOPIC_SUMMARY_HINTS = {
    "docker": "围绕 Docker 镜像、容器代理、本地环境和服务部署排障展开，重点是如何让服务稳定跑起来。",
    "端口": "讨论端口开放、访问入口、内外网连接和服务暴露方式，核心是能不能稳定访问。",
    "公网": "围绕公网访问、反代和外部入口连通性展开，大家在排查为什么外部访问不稳定。",
    "nas": "讨论 NAS、软路由、存储和家庭服务器环境，重点是资源放哪里、服务怎么部署。",
    "微信": "讨论微信登录、接口、安全限制和自动化控制，涉及账号保护和执行边界。",
    "https": "围绕 HTTPS、证书、反代和安全访问配置展开，重点是链路能不能正常访问。",
    "gpt": "讨论 AI 工具、模型接入和自动化能力，关注能否让机器人稳定帮忙处理任务。",
}

FONT_CANDIDATES = {
    "regular": [
        "/app/runtime/report-fonts/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/STHeiti Light.ttc",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        "/System/Library/Fonts/CJKSymbolsFallback.ttc",
        "/Library/Fonts/Arial Unicode.ttf",
    ],
    "bold": [
        "/app/runtime/report-fonts/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/STHeiti Medium.ttc",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        "/System/Library/Fonts/CJKSymbolsFallback.ttc",
        "/Library/Fonts/Arial Unicode.ttf",
    ],
}

COLOR = {
    "bg": "#f4f8f7",
    "ink": "#10241f",
    "muted": "#62776f",
    "line": "#d8e4df",
    "green": "#0aa47e",
    "green_dark": "#062923",
    "green_mid": "#14725f",
    "mint": "#e2f6ed",
    "deep": "#071c1b",
    "deep_2": "#0c3430",
    "cyan": "#4dd6c8",
    "white": "#ffffff",
    "gold": "#e7bd55",
    "gold_light": "#fff0aa",
    "gold_dark": "#9b6a18",
    "silver": "#bbc6ce",
    "bronze": "#c48349",
    "bronze_dark": "#7b4429",
    "soft_gold": "#fff4d6",
    "purple": "#6c4de6",
    "rose": "#d64b72",
}


@dataclass
class Message:
    uid: str
    local_id: int
    create_time: int
    time_text: str
    hour_text: str
    sender_key: str
    sender_name: str
    avatar_key: str
    type_label: str
    text: str
    is_self: bool


def local_dt(value: int) -> datetime:
    return datetime.fromtimestamp(int(value), DISPLAY_TZ)


def time_text(value: int, fmt: str = "%H:%M") -> str:
    return local_dt(value).strftime(fmt) if value else ""


def day_bounds(day: str) -> tuple[int, int, str]:
    if day:
        start = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=DISPLAY_TZ)
    else:
        now = datetime.now(DISPLAY_TZ)
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    return int(start.timestamp()), int(end.timestamp()), start.strftime("%Y-%m-%d")


def parse_datetime(value: str | int | float | None) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(int(value), DISPLAY_TZ)
    text = str(value).strip()
    if not text:
        return None
    if re.fullmatch(r"\d{10,13}", text):
        number = int(text[:10])
        return datetime.fromtimestamp(number, DISPLAY_TZ)
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(text, fmt)
            return parsed.replace(tzinfo=DISPLAY_TZ)
        except ValueError:
            continue
    try:
        parsed = datetime.fromisoformat(text)
        return parsed.astimezone(DISPLAY_TZ) if parsed.tzinfo else parsed.replace(tzinfo=DISPLAY_TZ)
    except ValueError:
        return None


def range_bounds(
    *,
    day: str = "",
    start_time: str | int | float | None = None,
    end_time: str | int | float | None = None,
    hours: int | float | None = None,
    now: datetime | None = None,
) -> tuple[int, int, str, str]:
    now = now or datetime.now(DISPLAY_TZ)
    explicit_start = parse_datetime(start_time)
    explicit_end = parse_datetime(end_time)
    if explicit_start:
        start = explicit_start
        end = explicit_end or now
        label = start.strftime("%Y-%m-%d %H:%M") + " 至 " + end.strftime("%Y-%m-%d %H:%M")
        return int(start.timestamp()), int(end.timestamp()), label, start.strftime("%Y-%m-%d")
    if hours:
        span = max(1, int(float(hours)))
        end = explicit_end or now
        start = end - timedelta(hours=span)
        label = f"近 {span} 小时 · {start.strftime('%m-%d %H:%M')}-{end.strftime('%H:%M')}"
        return int(start.timestamp()), int(end.timestamp()), label, now.strftime("%Y-%m-%d")
    if day:
        start_ts, end_ts, day_text = day_bounds(day)
        return start_ts, end_ts, f"{day_text} 00:00-23:59", day_text
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = explicit_end or now
    day_text = start.strftime("%Y-%m-%d")
    return int(start.timestamp()), int(end.timestamp()), f"{day_text} 00:00-{end.strftime('%H:%M')}", day_text


def count_messages_for_day(chat_username: str, day: str) -> int:
    start_ts, end_ts, _ = day_bounds(day)
    if not MEMORY_DB.exists():
        return 0
    try:
        with sqlite3.connect(MEMORY_DB) as conn:
            row = conn.execute(
                """
                SELECT COUNT(*)
                FROM messages
                WHERE chat_username=? AND COALESCE(create_time, 0)>=? AND COALESCE(create_time, 0)<?
                """,
                (chat_username, start_ts, end_ts),
            ).fetchone()
    except sqlite3.Error:
        return 0
    return int((row or [0])[0] or 0)


def resolve_report_day(chat_username: str, day: str = "") -> str:
    explicit = str(day or "").strip()
    if explicit:
        return explicit
    now = datetime.now(DISPLAY_TZ)
    today = now.strftime("%Y-%m-%d")
    if now.hour >= 4:
        return today
    yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
    today_count = count_messages_for_day(chat_username, today)
    yesterday_count = count_messages_for_day(chat_username, yesterday)
    if today_count < 20 and yesterday_count >= max(50, today_count * 3):
        return yesterday
    return today


def clean_text(value: str, limit: int = 120, ellipsis: bool = True) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    text = text.replace("\u2005", " ").replace("\u200b", "")
    if limit and len(text) > limit:
        return text[:limit].rstrip()
    return text


def display_safe_text(value: str, limit: int = 0) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = re.sub(r"[\U00010000-\U0010ffff\u200d\ufe0f]+", "", text)
    text = re.sub(r"[\u2600-\u27bf]+", "", text)
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return clean_text(text, limit, ellipsis=False) if limit else text


def text_fingerprint(value: str) -> str:
    text = clean_text(value, 0).lower()
    text = re.sub(r"https?://\S+", " URL ", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[\s，,。.!！?？:：;；、'\"“”‘’（）()【】\\[\\]{}<>《》|/\\\\_-]+", "", text)
    return text[:120]


def clean_sample_text(value: str) -> str:
    text = clean_text(value, 0)
    text = re.sub(r"(?:^|；)\s*引用\s+[^:：]{1,32}[:：]\s*", "；", text)
    text = re.sub(r"<\\?xml[^>]*>.*", "", text, flags=re.I)
    text = re.sub(r"https?://\S+", "[链接]", text)
    text = re.sub(r"\s*；\s*；+", "；", text)
    return text.strip("； ")


def invalid_topic_token(token: str) -> bool:
    text = clean_text(token, 0)
    lowered = text.lower()
    if not text or len(text) < 2:
        return True
    if lowered.startswith(("http", "www")) or "." in lowered or "/" in lowered:
        return True
    if re.search(r"[?&=]", text) or re.fullmatch(r"[a-z0-9_-]{8,}", lowered):
        return True
    if any(word in text for word in ("的东西", "的事", "几个", "睡觉", "在吗", "没事儿", "我刚写了", "我先听一下")):
        return True
    if re.fullmatch(r"[\u4e00-\u9fff]{1,2}", text) and text not in {"公网", "端口", "微信"}:
        return True
    return False


def short_name(value: str, limit: int = 12) -> str:
    text = display_safe_text(value, 80)
    if not text:
        return "群友"
    if not re.search(r"[A-Za-z0-9\u4e00-\u9fff]", text):
        return "群友"
    if len(text) > limit:
        return text[:limit].rstrip()
    return text


def looks_like_wechat_id(value: str) -> bool:
    text = display_safe_text(value, 80).lower()
    return bool(text and (text.startswith("wxid_") or text.endswith("@chatroom") or re.fullmatch(r"[a-z0-9_]{10,}", text)))


def group_display_name(username: str, contact: dict | None = None) -> str:
    contact = contact or {}
    for value in (
        contact.get("group_alias"),
        contact.get("nick_name"),
        contact.get("remark"),
        contact.get("alias"),
        contact.get("display_name"),
    ):
        text = display_safe_text(value, 80)
        if text and not looks_like_wechat_id(text):
            return text
    fallback = display_safe_text(username, 80)
    return "" if looks_like_wechat_id(fallback) else fallback


def decode_chatroom_members_buffer(buffer: bytes | None) -> dict[str, str]:
    if not buffer:
        return {}
    data = bytes(buffer)
    members: dict[str, str] = {}
    index = 0
    for _ in range(600):
        start = data.find(b"\n", index)
        if start < 0 or start + 2 >= len(data):
            break
        length = data[start + 1]
        name_start = start + 2
        name_end = name_start + length
        if length <= 0 or name_end > len(data):
            index = start + 1
            continue
        try:
            username = data[name_start:name_end].decode("utf-8")
        except UnicodeDecodeError:
            index = start + 1
            continue
        if not re.fullmatch(r"[A-Za-z0-9_@.\-]{2,80}", username):
            index = start + 1
            continue
        alias = ""
        cursor = name_end
        if cursor + 2 <= len(data) and data[cursor] == 0x12:
            alias_len = data[cursor + 1]
            alias_start = cursor + 2
            alias_end = alias_start + alias_len
            if alias_len and alias_end <= len(data):
                try:
                    alias = display_safe_text(data[alias_start:alias_end].decode("utf-8"), 80)
                except UnicodeDecodeError:
                    alias = ""
        members[username] = alias
        index = name_end
    return members


def contact_names(chat_username: str) -> dict[str, str]:
    if not CONTACT_DB.exists():
        return {}
    contacts: dict[str, dict] = {}
    aliases: dict[str, str] = {}
    try:
        with sqlite3.connect(CONTACT_DB) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT ext_buffer FROM chat_room WHERE username=?", (chat_username,)).fetchone()
            if row:
                aliases = decode_chatroom_members_buffer(row["ext_buffer"])
            rows = conn.execute(
                """
                SELECT c.username, c.remark, c.nick_name, c.alias
                FROM chatroom_member cm
                JOIN chat_room r ON r.id=cm.room_id
                JOIN contact c ON c.id=cm.member_id
                WHERE r.username=?
                """,
                (chat_username,),
            ).fetchall()
            for row in rows:
                username = str(row["username"] or "")
                if username:
                    contacts[username] = {
                        "username": username,
                        "remark": display_safe_text(row["remark"], 80),
                        "nick_name": display_safe_text(row["nick_name"], 80),
                        "alias": display_safe_text(row["alias"], 80),
                        "group_alias": aliases.get(username, ""),
                    }
    except sqlite3.Error:
        return {}
    for username, alias in aliases.items():
        contact = contacts.get(username, {"username": username})
        contact["group_alias"] = alias
        contacts[username] = contact
    return {
        username: group_display_name(username, contact) or "群友"
        for username, contact in contacts.items()
        if group_display_name(username, contact)
    }


def replace_contact_identity_tokens(value: str, names: dict[str, str]) -> str:
    text = str(value or "")
    if not text or not names:
        return text
    for username, display in sorted(names.items(), key=lambda item: len(item[0]), reverse=True):
        if not username or not display or username == display:
            continue
        escaped = re.escape(username)
        if re.fullmatch(r"[A-Za-z0-9_@.\-]+", username):
            text = re.sub(rf"(?<![A-Za-z0-9_@.\-]){escaped}(?![A-Za-z0-9_@.\-])", display, text)
        else:
            text = text.replace(username, display)
    return text


def avatar_bytes(username: str) -> bytes | None:
    username = str(username or "").strip()
    if not username or not HEAD_IMAGE_DB.exists():
        return None
    try:
        with sqlite3.connect(HEAD_IMAGE_DB) as conn:
            row = conn.execute("SELECT image_buffer FROM head_image WHERE username=? AND length(image_buffer)>0", (username,)).fetchone()
    except sqlite3.Error:
        return None
    if not row or not row[0]:
        return None
    return bytes(row[0])


def avatar_image(username: str, size: int):
    data = avatar_bytes(username)
    if not data:
        return None
    try:
        from PIL import Image

        return Image.open(io.BytesIO(data)).convert("RGBA").resize((size, size))
    except Exception:
        return None


def load_messages(chat_username: str, start_ts: int, end_ts: int) -> tuple[str, list[Message]]:
    contacts = contact_names(chat_username)
    with sqlite3.connect(MEMORY_DB) as conn:
        conn.row_factory = sqlite3.Row
        chat = conn.execute("SELECT display_name FROM chats WHERE username=?", (chat_username,)).fetchone()
        rows = conn.execute(
            """
            SELECT message_uid, local_id, create_time, real_sender_id, origin_source,
                   type_label, source, message_content, compress_content
            FROM messages
            WHERE chat_username=? AND COALESCE(create_time, 0)>=? AND COALESCE(create_time, 0)<?
            ORDER BY create_time ASC, local_id ASC
            """,
            (chat_username, start_ts, end_ts),
        ).fetchall()
    output: list[Message] = []
    for row in rows:
        data = dict(row)
        sender, text = message_index_text(data)
        sender_key = clean_text(sender, 120)
        is_self = False
        try:
            is_self = int(data.get("origin_source") or 0) == 1 and not sender_key
        except (TypeError, ValueError):
            is_self = False
        if not sender_key and is_self:
            sender_key = "wechatagent"
        sender_name = display_safe_text(contacts.get(sender_key) or ("WeChatAgent" if is_self else "群友"), 80)
        text = replace_contact_identity_tokens(text, contacts)
        output.append(
            Message(
                uid=str(data.get("message_uid") or ""),
                local_id=int(data.get("local_id") or 0),
                create_time=int(data.get("create_time") or 0),
                time_text=time_text(int(data.get("create_time") or 0)),
                hour_text=time_text(int(data.get("create_time") or 0), "%H:00"),
                sender_key=sender_key,
                sender_name=sender_name,
                avatar_key=sender_key,
                type_label=str(data.get("type_label") or "unknown"),
                text=display_safe_text(text, 360),
                is_self=is_self,
            )
        )
    return (str(chat["display_name"] or chat_username) if chat else chat_username), output


def topic_tokens(messages: list[Message]) -> Counter:
    counter: Counter[str] = Counter()
    text_messages = [
        msg
        for msg in messages
        if msg.type_label == "text"
        and msg.text
        and "当前微信版本不支持展示该内容" not in msg.text
        and not msg.text.startswith("向他人发起了一笔转账")
    ]
    joined = "\n".join(msg.text for msg in text_messages)
    for hint in TOPIC_HINTS:
        lowered = joined.lower()
        needle = hint.lower()
        if needle == "pt":
            count = len(re.findall(r"(?<![a-z0-9])pt(?![a-z0-9])", lowered))
        else:
            count = lowered.count(needle)
        if count:
            counter[hint] += count + 1
    for match in re.findall(r"[A-Za-z][A-Za-z0-9_+.\-]{2,}|[\u4e00-\u9fff]{2,8}", joined):
        token = match.strip()
        token_lower = token.lower()
        if token in STOPWORDS or token_lower in STOPWORDS:
            continue
        if token_lower.startswith(("http", "www")) or "." in token_lower:
            continue
        if invalid_topic_token(token):
            continue
        if re.fullmatch(r"\d+", token):
            continue
        if len(token) < 2:
            continue
        counter[token] += 1
    return counter


def representative_texts(messages: list[Message], keyword: str, limit: int = 2) -> list[str]:
    hits = []
    seen = set()
    key = keyword.lower()
    for msg in messages:
        if msg.is_self or msg.type_label != "text" or not msg.text:
            continue
        if "当前微信版本不支持展示该内容" in msg.text or msg.text.startswith("向他人发起了一笔转账"):
            continue
        cleaned = clean_sample_text(msg.text)
        if key in cleaned.lower():
            sample = f"{short_name(msg.sender_name, 8)}：{clean_text(cleaned, 260, ellipsis=False)}"
            fp = text_fingerprint(sample)
            if not fp or fp in seen:
                continue
            seen.add(fp)
            hits.append(sample)
        if len(hits) >= limit:
            break
    return hits


def topic_summary(topic: str, samples: list[str]) -> str:
    key = str(topic or "").lower()
    for hint, summary in TOPIC_SUMMARY_HINTS.items():
        if hint in key:
            return summary
    return "这个话题在群里有持续出现，代表片段会单独列出，便于回看上下文。"


def is_signal_text(msg: Message) -> bool:
    if msg.is_self or msg.type_label != "text" or not msg.text:
        return False
    if "当前微信版本不支持展示该内容" in msg.text:
        return False
    if msg.text.startswith("向他人发起了一笔转账"):
        return False
    if msg.text in {"[图片]", "[视频]", "[语音]", "[表情]"}:
        return False
    return True


def build_insights(messages: list[Message], topics: list[tuple[str, int]], leaders: dict, stats: dict) -> list[str]:
    insights = []
    topic_names = [topic for topic, _ in topics[:5]]
    if topic_names:
        insights.append(f"当天讨论主线集中在 {'、'.join(topic_names[:4])}，其中 {topic_names[0]} 的反复出现最明显。")
    if leaders.get("peak", {}).get("count"):
        insights.append(
            f"消息高峰出现在 {leaders['peak']['name']}，该小时约 {leaders['peak']['count']} 条，适合优先回看这一段。"
        )
    media_total = int(stats.get("images") or 0) + int(stats.get("videos") or 0) + int(stats.get("stickers") or 0)
    if media_total:
        insights.append(f"多媒体互动不少，图片/视频/表情合计 {media_total} 个，说明群里不只是纯文字讨论。")
    if stats.get("links"):
        insights.append(f"链接/文件共有 {stats['links']} 条，今天的信息交换偏实用，可以重点复盘链接前后的上下文。")
    if leaders.get("talk", {}).get("count"):
        insights.append(f"{leaders['talk']['name']} 发言最多，共 {leaders['talk']['count']} 条，是今天信息流里的主要推动者。")
    if not insights:
        insights.append("今天可见消息较少，暂时没有形成明显主线。")
    return insights[:5]


def build_quote_board(messages: list[Message], limit: int = 4) -> list[dict]:
    candidates = [
        msg
        for msg in messages
        if is_signal_text(msg)
        and 10 <= len(msg.text) <= 420
        and not re.fullmatch(r"[\W_]+", msg.text)
    ]
    candidates.sort(key=lambda msg: (len(set(msg.text)), len(msg.text)), reverse=True)
    selected = []
    seen = set()
    for msg in candidates:
        key = re.sub(r"\W+", "", msg.text)[:24]
        if not key or key in seen:
            continue
        seen.add(key)
        selected.append(
            {
                "time": msg.time_text,
                "speaker": short_name(msg.sender_name, 8),
                "text": clean_text(msg.text, 360, ellipsis=False),
            }
        )
        if len(selected) >= limit:
            break
    return selected


def build_timeline(messages: list[Message], topics: list[tuple[str, int]], limit: int = 6) -> list[dict]:
    by_hour: dict[str, list[Message]] = defaultdict(list)
    for msg in messages:
        if msg.is_self:
            continue
        by_hour[msg.hour_text].append(msg)
    topic_words = [topic for topic, _ in topics[:8]]
    rows = []
    for hour, items in sorted(by_hour.items()):
        text_items = [item for item in items if is_signal_text(item)]
        if not text_items:
            continue
        score = len(items)
        matched = []
        for word in topic_words:
            if any(word.lower() in item.text.lower() for item in text_items):
                matched.append(word)
                score += 20
        sample = max(text_items, key=lambda item: len(item.text))
        rows.append(
            {
                "hour": hour,
                "score": score,
                "topics": matched[:3],
                "speaker": short_name(sample.sender_name, 8),
                "text": clean_text(sample.text, 240, ellipsis=False),
                "count": len(items),
            }
        )
    rows.sort(key=lambda item: item["score"], reverse=True)
    selected = sorted(rows[:limit], key=lambda item: item["hour"])
    return selected


def build_report(
    chat_username: str,
    day: str = "",
    *,
    start_time: str | int | float | None = None,
    end_time: str | int | float | None = None,
    hours: int | float | None = None,
    llm_summary: dict | None = None,
) -> dict:
    start_ts, end_ts, range_label, day_text = range_bounds(day=day, start_time=start_time, end_time=end_time, hours=hours)
    chat_display, messages = load_messages(chat_username, start_ts, end_ts)
    user_messages = [msg for msg in messages if not msg.is_self]
    senders = Counter(msg.sender_key for msg in user_messages if msg.sender_key)
    sender_names = {msg.sender_key: msg.sender_name for msg in user_messages if msg.sender_key}
    type_counts = Counter(msg.type_label for msg in user_messages)
    user_type_counts = Counter(msg.type_label for msg in user_messages)
    topics = topic_tokens(user_messages).most_common(10)
    timeline = build_timeline(user_messages, topics, 6)
    hourly = Counter(msg.hour_text for msg in user_messages)
    peak_hour, peak_count = ("--", 0)
    if hourly:
        peak_hour, peak_count = hourly.most_common(1)[0]
    active_rank = [
        {"username": key, "avatar_key": key, "name": short_name(sender_names.get(key) or key, 12), "count": count}
        for key, count in senders.most_common(8)
    ]
    media_leader = Counter(
        msg.sender_key
        for msg in user_messages
        if msg.sender_key and msg.type_label in {"image", "sticker", "video"}
    )
    link_leader = Counter(msg.sender_key for msg in user_messages if msg.sender_key and msg.type_label == "link_or_file")
    topic_cards = []
    for topic, count in topics[:6]:
        samples = representative_texts(user_messages, topic, 2)
        topic_cards.append(
            {
                "topic": topic,
                "count": count,
                "summary": topic_summary(topic, samples),
                "samples": samples,
            }
        )
    one_line_bits = []
    if topics:
        one_line_bits.append("、".join(topic for topic, _ in topics[:4]))
    if peak_count:
        one_line_bits.append(f"{peak_hour} 最热闹")
    if type_counts.get("image") or type_counts.get("link_or_file"):
        one_line_bits.append(f"图片 {type_counts.get('image', 0)} 张、链接/文件 {type_counts.get('link_or_file', 0)} 条")
    one_line = "今天主线集中在" + "；".join(one_line_bits) + "。" if one_line_bits else "今天可见消息较少，暂时没有形成明显主线。"
    range_text = range_label
    leaders = {
        "talk": active_rank[0] if active_rank else {"name": "--", "count": 0},
        "media": {
            "name": short_name(sender_names.get(media_leader.most_common(1)[0][0]) or media_leader.most_common(1)[0][0], 12),
            "count": media_leader.most_common(1)[0][1],
        }
        if media_leader
        else {"name": "--", "count": 0},
        "link": {
            "name": short_name(sender_names.get(link_leader.most_common(1)[0][0]) or link_leader.most_common(1)[0][0], 12),
            "count": link_leader.most_common(1)[0][1],
        }
        if link_leader
        else {"name": "--", "count": 0},
        "peak": {"name": peak_hour, "count": peak_count},
    }
    stats = {
        "messages": len(user_messages),
        "members": len(senders),
        "text": type_counts.get("text", 0),
        "images": type_counts.get("image", 0),
        "stickers": type_counts.get("sticker", 0),
        "links": type_counts.get("link_or_file", 0),
        "videos": type_counts.get("video", 0),
        "bot_messages": sum(1 for msg in messages if msg.is_self),
    }
    llm_summary = llm_summary if isinstance(llm_summary, dict) else {}
    if llm_summary:
        one_line = clean_text(llm_summary.get("one_line") or one_line, 280, ellipsis=False)
        insights = [
            clean_text(str(item), 380, ellipsis=False)
            for item in (llm_summary.get("insights") or [])
            if str(item or "").strip()
        ][:6] or build_insights(user_messages, topics, leaders, stats)
        topic_cards = [
            {
                "topic": clean_text(item.get("topic") or f"话题 {idx}", 24, ellipsis=False),
                "count": item.get("count") or 0,
                "summary": clean_text(item.get("summary") or "", 460, ellipsis=False),
                "samples": [
                    clean_text(str(sample), 360, ellipsis=False)
                    for sample in (item.get("samples") or [])
                    if str(sample or "").strip()
                ][:2],
            }
            for idx, item in enumerate(llm_summary.get("topics") or [], 1)
            if isinstance(item, dict)
        ][:6] or topic_cards
        quotes = [
            {
                "time": clean_text(item.get("time") or "", 16, ellipsis=False),
                "speaker": short_name(item.get("speaker") or "", 10),
                "text": clean_text(item.get("text") or "", 420, ellipsis=False),
            }
            for item in (llm_summary.get("quotes") or [])
            if isinstance(item, dict) and str(item.get("text") or "").strip()
        ][:4] or build_quote_board(user_messages, 4)
    else:
        insights = build_insights(user_messages, topics, leaders, stats)
        quotes = build_quote_board(user_messages, 4)

    return {
        "chat_username": chat_username,
        "chat_display": chat_display,
        "day": day_text,
        "range_text": range_text,
        "generated_at": datetime.now(DISPLAY_TZ).strftime("%Y-%m-%d %H:%M"),
        "one_line": one_line,
        "stats": stats,
        "user_type_counts": dict(user_type_counts),
        "insights": insights,
        "topics": topic_cards,
        "timeline": timeline,
        "quotes": quotes,
        "active_rank": active_rank,
        "leaders": leaders,
    }


def esc(value) -> str:
    return html.escape(str(value or ""), quote=True)


def stat_cell(label: str, value, unit: str) -> str:
    return f"<div class='stat'><span>{esc(label)}</span><b>{esc(value)}</b><em>{esc(unit)}</em></div>"


def strip_number_prefix(value: str) -> str:
    return re.sub(r"^\s*\d+[.、)]\s*", "", str(value or "")).strip()


def render_html(report: dict) -> str:
    stats = report["stats"]
    insight_html = "\n".join(
        f"<li><span>{idx}</span><p>{esc(strip_number_prefix(str(item)))}</p></li>"
        for idx, item in enumerate(report.get("insights") or [], 1)
    )
    topics_html = "\n".join(
        f"""
        <section class="topic">
          <div class="topic-head"><b>{esc(item['topic'])}</b><span>出现 {esc(item['count'])} 次</span></div>
          <p>{esc('；'.join(item['samples']) if item['samples'] else '有讨论热度，但片段较分散。')}</p>
        </section>
        """
        for item in report["topics"]
    )
    timeline_html = "\n".join(
        f"""
        <div class="time-row">
          <b>{esc(item['hour'])}</b>
          <div><strong>{esc(' / '.join(item['topics']) if item['topics'] else item['speaker'])}</strong><p>{esc(item['text'])}</p></div>
          <span>{esc(item['count'])} 条</span>
        </div>
        """
        for item in report["timeline"]
    )
    rank_html = "\n".join(
        f"<li class='rank-{idx}'><span>{'♕' if idx == 1 else '♔' if idx in (2, 3) else idx}</span><i>{esc(short_name(item['name'], 2))}</i><b>{esc(item['name'])}</b><em>{esc(item['count'])} 条</em></li>"
        for idx, item in enumerate(report["active_rank"][:6], 1)
    )
    leaders = report["leaders"]
    leader_html = "\n".join(
        [
            stat_cell("发言最多", leaders["talk"]["name"], f"{leaders['talk']['count']} 条"),
            stat_cell("媒体贡献", leaders["media"]["name"], f"{leaders['media']['count']} 个"),
            stat_cell("链接贡献", leaders["link"]["name"], f"{leaders['link']['count']} 条"),
            stat_cell("高峰时段", leaders["peak"]["name"], f"{leaders['peak']['count']} 条"),
        ]
    )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<style>
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0;
    width: 920px;
    background: #eef5f0;
    color: #10251f;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
  }}
  .page {{
    width: 920px;
    padding: 48px 54px 42px;
    background:
      radial-gradient(circle at 92% 0%, rgba(79, 190, 156, .22), transparent 26%),
      linear-gradient(180deg, #fbfffc, #eef7f2 70%, #e7f0eb);
  }}
	  .brand {{ color: #ffe9a6; font-size: 16px; font-weight: 900; letter-spacing: 2.4px; text-transform: uppercase; }}
	  .hero {{ padding: 30px 34px; border: 3px solid #e7bd55; border-radius: 28px; background: radial-gradient(circle at 85% 15%, rgba(231,189,85,.32), transparent 28%), linear-gradient(135deg, #071c1b, #0c3430); color: #fff; }}
	  h1 {{ margin: 18px 0 10px; font-size: 46px; line-height: 1.08; letter-spacing: 0; }}
	  .meta {{ color: #b8eee6; font-size: 20px; font-weight: 800; line-height: 1.7; }}
	  .rule {{ height: 5px; margin: 30px 0 30px; background: linear-gradient(90deg, #e7bd55, #6fd6b5, transparent); border-radius: 999px; }}
  h2 {{ margin: 0 0 16px; font-size: 28px; }}
  .block {{ padding: 26px 0; border-bottom: 1px solid rgba(16, 37, 31, .12); }}
  .lead {{ font-size: 24px; line-height: 1.55; font-weight: 850; }}
	  .bullets {{ margin: 0; padding-left: 0; list-style: none; display: grid; gap: 14px; }}
	  .bullets li {{ display: grid; grid-template-columns: 44px 1fr; gap: 14px; align-items: start; padding: 16px; border: 1px solid #e7bd55; border-radius: 18px; background: #fffdf4; }}
	  .bullets span {{ width: 38px; height: 38px; border-radius: 12px; display: grid; place-items: center; background: #071c1b; color: #ffe9a6; font-size: 20px; font-weight: 950; }}
	  .bullets p {{ margin: 0; font-size: 21px; line-height: 1.45; font-weight: 800; }}
  .stats {{ display: grid; grid-template-columns: repeat(3, 1fr); border: 1px solid rgba(16,37,31,.42); }}
  .stat {{ min-height: 118px; padding: 18px; border-right: 1px solid rgba(16,37,31,.32); border-bottom: 1px solid rgba(16,37,31,.32); background: rgba(255,255,255,.42); }}
  .stat:nth-child(3n) {{ border-right: 0; }}
  .stat:nth-last-child(-n+3) {{ border-bottom: 0; }}
  .stat span {{ display: block; color: #667970; font-size: 15px; font-weight: 900; }}
  .stat b {{ display: block; margin-top: 6px; font-size: 34px; line-height: 1; }}
  .stat em {{ color: #416056; font-size: 16px; font-style: normal; font-weight: 800; }}
  .topics {{ display: grid; gap: 14px; }}
  .topic {{ padding-left: 17px; border-left: 6px solid #16795e; }}
  .topic-head {{ display: flex; align-items: baseline; gap: 12px; }}
  .topic-head b {{ font-size: 22px; }}
  .topic-head span {{ color: #667970; font-size: 15px; font-weight: 850; }}
  .topic p {{ margin: 6px 0 0; color: #273d36; font-size: 18px; line-height: 1.38; font-weight: 700; }}
  .time-list {{ display: grid; gap: 17px; }}
  .time-row {{ display: grid; grid-template-columns: 86px minmax(0,1fr) 74px; gap: 17px; align-items: start; }}
  .time-row > b {{ color: #0f6f59; font-size: 21px; }}
  .time-row strong {{ font-size: 19px; }}
  .time-row p {{ margin: 5px 0 0; color: #344940; font-size: 18px; font-weight: 700; line-height: 1.35; }}
  .time-row span {{ text-align: right; color: #6a7b73; font-weight: 850; }}
  .leader-grid {{ display: grid; grid-template-columns: repeat(2, 1fr); border: 1px solid rgba(16,37,31,.42); }}
  .leader-grid .stat {{ min-height: 104px; }}
  .leader-grid .stat:nth-child(2n) {{ border-right: 0; }}
  .leader-grid .stat:nth-last-child(-n+2) {{ border-bottom: 0; }}
	  .rank {{ margin: 0; padding: 0; list-style: none; display: grid; gap: 10px; }}
	  .rank li {{ display: grid; grid-template-columns: 42px 44px 1fr 96px; gap: 12px; align-items: center; min-height: 58px; padding: 9px 12px; border: 1px solid rgba(16,37,31,.16); border-radius: 16px; background: #fff; font-size: 19px; font-weight: 850; }}
	  .rank li.rank-1 {{ min-height: 76px; border-color: #e7bd55; background: #fff8df; box-shadow: inset 0 0 0 2px #fff0aa; }}
	  .rank li.rank-2 {{ border-color: #bbc6ce; background: #f4f7f8; }}
	  .rank li.rank-3 {{ border-color: #c48349; background: #fff1e8; }}
	  .rank span {{ color: #9b6a18; font-size: 28px; text-align: center; }}
	  .rank i {{ width: 42px; height: 42px; border-radius: 999px; display: grid; place-items: center; background: #071c1b; color: #fff; border: 3px solid #e7bd55; font-style: normal; }}
	  .rank em {{ color: #4d6259; text-align: right; font-style: normal; }}
  .note {{ color: #5c6f66; font-size: 17px; line-height: 1.5; font-weight: 700; }}
  .footer {{ margin-top: 24px; color: #3f5c52; font-size: 16px; font-weight: 850; }}
</style>
</head>
<body>
<main class="page">
  <section class="hero">
    <div class="brand">WECHATAGENT · GROUP INTEL REPORT</div>
    <h1>{esc(report['chat_display'])}<br>群聊日报</h1>
    <div class="meta">统计范围：{esc(report['range_text'])}<br>生成时间：{esc(report['generated_at'])}</div>
  </section>
  <div class="rule"></div>

  <section class="block">
    <h2>一句话总结</h2>
    <p class="lead">{esc(report['one_line'])}</p>
  </section>

  <section class="block">
    <h2>干货总结</h2>
    <ul class="bullets">{insight_html or '<li><span>1</span><p>今天可见消息较少，暂无足够总结。</p></li>'}</ul>
  </section>

  <section class="block">
    <div class="stats">
      {stat_cell('消息总量', stats['messages'], '条')}
      {stat_cell('参与成员', stats['members'], '人')}
      {stat_cell('文本消息', stats['text'], '条')}
      {stat_cell('图片', stats['images'], '张')}
      {stat_cell('表情', stats['stickers'], '个')}
      {stat_cell('链接/文件', stats['links'], '条')}
    </div>
  </section>

  <section class="block">
    <h2>主要话题</h2>
    <div class="topics">{topics_html or '<p class="note">暂无足够话题数据。</p>'}</div>
  </section>

  <section class="block">
    <h2>关键时间线</h2>
    <div class="time-list">{timeline_html or '<p class="note">暂无足够时间线数据。</p>'}</div>
  </section>

  <section class="block">
    <h2>活跃成员</h2>
    <div class="leader-grid">{leader_html}</div>
  </section>

  <section class="block">
    <h2>发言排行</h2>
    <ol class="rank">{rank_html or '<li><b>暂无</b></li>'}</ol>
  </section>

  <section class="block">
    <h2>数据说明</h2>
    <p class="note">本日报由 WeChatAgent 基于本地已同步的微信群消息生成，只读取消息索引与本地群聊记录；图片、视频、文件只统计数量，不分析具体内容。</p>
  </section>
  <div class="footer">由 WeChatAgent 生成 · 本地群聊记忆日报</div>
  <script id="wechatagent-report-data" type="application/json">{html.escape(json.dumps(report, ensure_ascii=False), quote=False)}</script>
</main>
</body>
</html>"""


def hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = str(value or "").strip().lstrip("#")
    if len(value) != 6:
        return (0, 0, 0)
    return tuple(int(value[index : index + 2], 16) for index in (0, 2, 4))


def font_path(weight: str = "regular") -> str | None:
    for item in FONT_CANDIDATES.get(weight, []) + FONT_CANDIDATES["regular"]:
        if Path(item).exists():
            return item
    return None


def load_font(size: int, weight: str = "regular"):
    from PIL import ImageFont

    path = font_path(weight)
    if path:
        try:
            return ImageFont.truetype(path, size=size)
        except OSError:
            pass
    return ImageFont.load_default()


def text_width(draw, text: str, font) -> int:
    text = display_safe_text(text)
    if not text:
        return 0
    box = draw.textbbox((0, 0), str(text), font=font)
    return max(0, box[2] - box[0])


def wrap_text(draw, text: str, font, width: int, max_lines: int = 0) -> list[str]:
    text = display_safe_text(text)
    if not text:
        return []
    lines: list[str] = []
    current = ""
    for char in text:
        candidate = current + char
        if text_width(draw, candidate, font) <= width or not current:
            current = candidate
        else:
            lines.append(current)
            current = char
            if max_lines and len(lines) >= max_lines:
                break
    if current and (not max_lines or len(lines) < max_lines):
        lines.append(current)
    if max_lines and len(lines) > max_lines:
        lines = lines[:max_lines]
    if max_lines and len(lines) == max_lines and text_width(draw, "".join(lines), font) < text_width(draw, text, font):
        tail = lines[-1]
        while tail and text_width(draw, tail, font) > width:
            tail = tail[:-1]
        lines[-1] = tail or lines[-1][:1]
    return lines


def rounded_rectangle(draw, xy, radius: int, fill, outline=None, width: int = 1) -> None:
    draw.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline, width=width)


def draw_wrapped(draw, xy, text: str, font, fill, width: int, line_gap: int = 8, max_lines: int = 0) -> int:
    x, y = xy
    lines = wrap_text(draw, text, font, width, max_lines=max_lines)
    line_height = int(font.size * 1.28)
    for line in lines:
        draw.text((x, y), line, font=font, fill=fill)
        y += line_height + line_gap
    return y


def draw_badge(draw, xy, text: str, font, fill: str, outline: str) -> int:
    x, y = xy
    text = display_safe_text(text)
    pad_x = 14
    pad_y = 7
    w = text_width(draw, text, font) + pad_x * 2
    h = font.size + pad_y * 2 + 3
    rounded_rectangle(draw, (x, y, x + w, y + h), 14, hex_to_rgb(fill), hex_to_rgb(outline), 1)
    draw.text((x + pad_x, y + pad_y - 1), text, font=font, fill=hex_to_rgb(COLOR["green_dark"]))
    return w


def draw_crown(draw, x: int, y: int, w: int, h: int, fill, outline) -> None:
    points = [
        (x, y + h),
        (x + int(w * 0.16), y + int(h * 0.36)),
        (x + int(w * 0.34), y + int(h * 0.72)),
        (x + w // 2, y),
        (x + int(w * 0.66), y + int(h * 0.72)),
        (x + int(w * 0.84), y + int(h * 0.36)),
        (x + w, y + h),
    ]
    draw.polygon(points, fill=fill, outline=outline)
    draw.rounded_rectangle((x + 3, y + h - 8, x + w - 3, y + h + 3), radius=4, fill=fill, outline=outline, width=1)


def draw_avatar_frame(image, draw, cx: int, cy: int, radius: int, idx: int, initials: str, font, avatar_key: str = "") -> None:
    palette = [
        ("gold", "gold_light", "#fff8df", 6),
        ("silver", "white", "#eef3f5", 5),
        ("bronze", "soft_gold", "#fff4ea", 5),
        ("green", "white", "#edf7f2", 3),
    ]
    outline, accent, fill, width = palette[idx - 1] if idx <= 3 else palette[-1]
    glow = color_value("gold_light" if idx == 1 else accent)
    for offset in (10, 6):
        draw.ellipse((cx - radius - offset, cy - radius - offset, cx + radius + offset, cy + radius + offset), outline=glow, width=2)
    draw.ellipse((cx - radius - 3, cy - radius - 3, cx + radius + 3, cy + radius + 3), fill=color_value(fill), outline=color_value(outline), width=width)
    inner = (cx - radius + 8, cy - radius + 8, cx + radius - 8, cy + radius - 8)
    avatar_size = max(1, inner[2] - inner[0])
    avatar = avatar_image(avatar_key, avatar_size)
    if avatar:
        from PIL import Image, ImageDraw

        mask = Image.new("L", (avatar_size, avatar_size), 0)
        mask_draw = ImageDraw.Draw(mask)
        mask_draw.ellipse((0, 0, avatar_size - 1, avatar_size - 1), fill=255)
        image.paste(avatar, (inner[0], inner[1]), mask)
        draw.ellipse(inner, outline=color_value(accent), width=2)
    else:
        draw.ellipse(inner, fill=color_value("deep"), outline=color_value(accent), width=2)
        label = short_name(initials, 2) or "群"
        draw.text((cx - text_width(draw, label, font) // 2, cy - font.size // 2 - 2), label, font=font, fill=color_value("white"))


def color_value(color: str) -> tuple[int, int, int]:
    return hex_to_rgb(COLOR.get(color, color))


def draw_card(draw, xy, w: int, h: int, fill: str = "white", outline: str = "line", radius: int = 22) -> None:
    rounded_rectangle(draw, (xy[0], xy[1], xy[0] + w, xy[1] + h), radius, color_value(fill), color_value(outline), 2)


def render_png_pillow(report: dict, output: Path) -> None:
    from PIL import Image, ImageDraw

    if not font_path("regular"):
        raise RuntimeError("未找到可用中文字体，无法直接渲染日报 PNG")
    output.parent.mkdir(parents=True, exist_ok=True)
    width = 1080
    margin = 58
    content_w = width - margin * 2
    scratch = Image.new("RGB", (width, 2000), hex_to_rgb(COLOR["bg"]))
    draw = ImageDraw.Draw(scratch)
    fonts = {
        "brand": load_font(25, "bold"),
        "title": load_font(56, "bold"),
        "title_small": load_font(34, "bold"),
        "h2": load_font(32, "bold"),
        "h3": load_font(26, "bold"),
        "body": load_font(24, "regular"),
        "body_bold": load_font(24, "bold"),
        "small": load_font(20, "regular"),
        "small_bold": load_font(20, "bold"),
        "num": load_font(42, "bold"),
        "rank": load_font(30, "bold"),
        "avatar": load_font(22, "bold"),
    }

    y = 0
    pieces: list[tuple] = []

    def reserve(amount: int = 0) -> int:
        nonlocal y
        current = y
        y += amount
        return current

    y = 42
    hero_y = reserve(276)
    pieces.append(("hero", (margin, hero_y, content_w, 238)))
    pieces.append(("text", (margin + 36, hero_y + 30), "WECHATAGENT · MEMORY INTEL REPORT", fonts["brand"], "gold_light"))
    pieces.append(("wrapped", (margin + 36, hero_y + 72), f"{report['chat_display']} 群聊日报", fonts["title"], "white", content_w - 72, 4, 0))
    pieces.append(("text", (margin + 36, hero_y + 188), f"统计范围：{report['range_text']}", fonts["small_bold"], "cyan"))
    pieces.append(("text", (margin + 572, hero_y + 188), f"生成：{report['generated_at']}", fonts["small_bold"], "silver"))

    one_lines = wrap_text(draw, report["one_line"], fonts["body_bold"], content_w - 62, max_lines=0)
    card_h = max(148, 64 + len(one_lines) * 39)
    card_y = reserve(card_h + 18)
    pieces.append(("summary_card", (margin, card_y, content_w, card_h)))
    pieces.append(("badge", (margin + 28, card_y + 22), "一句话总结"))
    pieces.append(("wrapped", (margin + 28, card_y + 68), report["one_line"], fonts["body_bold"], "ink", content_w - 62, 8, 0))

    y += 20
    h2_y = reserve(46)
    pieces.append(("text", (margin, h2_y), "干货总结", fonts["h2"], COLOR["ink"]))
    insight_start = y
    for idx, insight in enumerate(report.get("insights") or [], 1):
        text = re.sub(r"^\s*\d+[.、]\s*", "", str(insight))
        lines = wrap_text(draw, text, fonts["body_bold"], content_w - 112, max_lines=0)
        row_h = max(78, len(lines) * 34 + 28)
        row_y = reserve(row_h + 10)
        pieces.append(("insight", (margin, row_y, content_w, row_h), idx, text))
    if y == insight_start:
        row_y = reserve(52)
        pieces.append(("wrapped", (margin, row_y), "今天可见消息较少，暂无足够总结。", fonts["body"], COLOR["muted"], content_w, 4, 0))

    y += 30
    stats = report["stats"]
    stat_items = [
        ("消息总量", stats["messages"], "条"),
        ("参与成员", stats["members"], "人"),
        ("文本消息", stats["text"], "条"),
        ("图片", stats["images"], "张"),
        ("表情", stats["stickers"], "个"),
        ("链接/文件", stats["links"], "条"),
    ]
    grid_y = reserve(270)
    col_w = (content_w - 24) // 3
    row_h = 122
    for idx, (label, value, unit) in enumerate(stat_items):
        col = idx % 3
        row = idx // 3
        x = margin + col * (col_w + 12)
        yy = grid_y + row * (row_h + 14)
        pieces.append(("card", (x, yy, col_w, row_h), "white", "line", 18))
        pieces.append(("text", (x + 20, yy + 18), label, fonts["small_bold"], COLOR["muted"]))
        pieces.append(("text", (x + 20, yy + 48), str(value), fonts["num"], COLOR["green_dark"]))
        pieces.append(("text", (x + col_w - 56, yy + 72), unit, fonts["small_bold"], COLOR["green_mid"]))

    y += 22
    topics = report.get("topics") or []
    h2_y = reserve(48)
    pieces.append(("text", (margin, h2_y), "主要话题", fonts["h2"], COLOR["ink"]))
    for idx, item in enumerate(topics[:6], 1):
        summary = item.get("summary") or "；".join(item.get("samples") or []) or "有讨论热度。"
        samples = "；".join(item.get("samples") or [])
        body = summary if not samples else f"{summary}｜{samples}"
        lines = wrap_text(draw, body, fonts["small_bold"], content_w - 92, max_lines=0)
        row_h = 90 + len(lines) * 31
        row_y = reserve(row_h + 12)
        pieces.append(("topic_line", (margin, row_y, content_w, row_h), idx, item))
        pieces.append(("wrapped", (margin + 60, row_y + 48), body, fonts["small_bold"], "ink", content_w - 92, 3, 0))
    if not topics:
        row_y = reserve(52)
        pieces.append(("wrapped", (margin, row_y), "暂无足够话题数据。", fonts["body"], COLOR["muted"], content_w, 4, 0))

    quotes = report.get("quotes") or []
    if quotes:
        y += 18
        h2_y = reserve(48)
        pieces.append(("text", (margin, h2_y), "代表片段", fonts["h2"], COLOR["ink"]))
        for quote in quotes[:4]:
            q_lines = wrap_text(draw, quote["text"], fonts["small_bold"], content_w - 44, max_lines=0)
            q_h = max(96, 56 + len(q_lines) * 30)
            row_y = reserve(q_h + 14)
            pieces.append(("card", (margin, row_y, content_w, q_h), "white", "line", 18))
            pieces.append(("text", (margin + 22, row_y + 18), f"{quote['time']} · {quote['speaker']}", fonts["small_bold"], COLOR["green_mid"]))
            pieces.append(("wrapped", (margin + 22, row_y + 50), quote["text"], fonts["small_bold"], "ink", content_w - 44, 3, 0))

    y += 18
    h2_y = reserve(48)
    pieces.append(("text", (margin, h2_y), "关键时间线", fonts["h2"], COLOR["ink"]))
    for item in report.get("timeline") or []:
        topic = " / ".join(item.get("topics") or []) or item.get("speaker") or ""
        t_lines = wrap_text(draw, item.get("text") or "", fonts["small_bold"], content_w - 240, max_lines=0)
        row_h = max(104, 64 + len(t_lines) * 27)
        row_y = reserve(row_h + 10)
        pieces.append(("timeline", (margin, row_y, content_w, row_h), item, topic))

    y += 18
    h2_y = reserve(48)
    pieces.append(("text", (margin, h2_y), "活跃成员 · 水王榜", fonts["h2"], COLOR["ink"]))
    rank_y = y
    for idx, item in enumerate((report.get("active_rank") or [])[:8], 1):
        row_h = 88 if idx <= 3 else 66
        row_y = reserve(row_h + 10)
        pieces.append(("rank", (margin, row_y, content_w, row_h), idx, item))
    if y == rank_y:
        row_y = reserve(52)
        pieces.append(("text", (margin, row_y), "暂无发言排行。", fonts["body"], COLOR["muted"]))

    y += 26
    note_y = reserve(112)
    pieces.append(("rule", (margin, note_y, margin + content_w, note_y + 2), "line"))
    pieces.append(("text", (margin, note_y + 28), "数据说明", fonts["h3"], COLOR["ink"]))
    pieces.append(
        (
            "wrapped",
            (margin, note_y + 66),
            "本日报由 WeChatAgent 基于本地已同步的微信群消息生成；图片、视频、文件只统计数量，不分析具体内容。",
            fonts["small_bold"],
            COLOR["muted"],
            content_w,
            5,
            0,
        )
    )
    footer_y = reserve(52)
    pieces.append(("text", (margin, footer_y), "由 WeChatAgent 生成 · 本地群聊记忆日报", fonts["small_bold"], COLOR["green_dark"]))

    height = y + 42
    image = Image.new("RGB", (width, height), hex_to_rgb(COLOR["bg"]))
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, width, height), fill=hex_to_rgb(COLOR["bg"]))
    draw.ellipse((width - 210, -120, width + 80, 170), fill=hex_to_rgb("#e4f3ef"))

    for piece in pieces:
        kind = piece[0]
        if kind == "hero":
            _, (x, yy, w, h) = piece
            draw.rounded_rectangle((x, yy, x + w, yy + h), radius=30, fill=color_value("deep"), outline=color_value("gold"), width=4)
            draw.rounded_rectangle((x + 12, yy + 12, x + w - 12, yy + h - 12), radius=24, outline=hex_to_rgb("#1d5e55"), width=2)
            draw.rounded_rectangle((x + 22, yy + 22, x + w - 22, yy + h - 22), radius=18, outline=hex_to_rgb("#324238"), width=1)
            draw.ellipse((x + w - 250, yy - 90, x + w + 80, yy + 240), fill=hex_to_rgb("#123f38"))
            draw.ellipse((x + w - 190, yy - 26, x + w + 22, yy + 186), outline=color_value("gold"), width=5)
            draw.ellipse((x + w - 152, yy + 12, x + w - 16, yy + 148), outline=color_value("cyan"), width=2)
            draw_crown(draw, x + w - 126, yy + 58, 76, 42, color_value("gold"), color_value("gold_light"))
        elif kind == "text":
            _, xy, text, font, color = piece
            draw.text(xy, display_safe_text(text), font=font, fill=color_value(color))
        elif kind == "wrapped":
            _, xy, text, font, color, max_w, gap, max_lines = piece
            draw_wrapped(draw, xy, text, font, color_value(color), max_w, gap, max_lines)
        elif kind == "rule":
            _, xy, color = piece
            draw.rounded_rectangle(xy, radius=4, fill=color_value(color))
        elif kind == "card":
            _, (x, yy, w, h), fill, outline, radius = piece
            draw_card(draw, (x, yy), w, h, fill, outline, radius)
        elif kind == "summary_card":
            _, (x, yy, w, h) = piece
            draw.rounded_rectangle((x, yy, x + w, yy + h), radius=24, fill=color_value("mint"), outline=color_value("gold"), width=3)
            draw.rounded_rectangle((x + 10, yy + 10, x + w - 10, yy + h - 10), radius=18, outline=hex_to_rgb("#d9c06f"), width=1)
            draw.rectangle((x, yy + h - 8, x + w, yy + h), fill=color_value("gold"))
        elif kind == "badge":
            _, xy, text = piece
            draw_badge(draw, xy, text, fonts["small_bold"], COLOR["soft_gold"], COLOR["gold"])
        elif kind == "bullet":
            _, (x, yy), color = piece
            draw.rounded_rectangle((x, yy, x + 15, yy + 15), radius=4, fill=color_value(color))
        elif kind == "num_bullet":
            _, (x, yy), idx = piece
            draw.rounded_rectangle((x, yy, x + 40, yy + 40), radius=13, fill=color_value("deep"), outline=color_value("gold"), width=2)
            draw.text((x + 20 - text_width(draw, str(idx), fonts["small_bold"]) // 2, yy + 7), str(idx), font=fonts["small_bold"], fill=color_value("gold"))
        elif kind == "insight":
            _, (x, yy, w, h), idx, text = piece
            outline = "gold" if idx == 1 else "green" if idx <= 3 else "line"
            fill = "#fffdf4" if idx == 1 else "white"
            draw.rounded_rectangle((x, yy, x + w, yy + h), radius=20, fill=color_value(fill), outline=color_value(outline), width=2)
            draw.rounded_rectangle((x + 10, yy + 10, x + 52, yy + h - 10), radius=14, fill=color_value("deep"), outline=color_value("gold"), width=2)
            draw.text((x + 31 - text_width(draw, str(idx), fonts["small_bold"]) // 2, yy + h // 2 - 13), str(idx), font=fonts["small_bold"], fill=color_value("gold_light"))
            draw.rounded_rectangle((x + 66, yy + 18, x + 134, yy + 45), radius=10, fill=color_value("soft_gold"), outline=color_value("gold"), width=1)
            draw.text((x + 80, yy + 20), "金标", font=fonts["small"], fill=color_value("gold_dark"))
            draw_wrapped(draw, (x + 146, yy + 18), text, fonts["body_bold"], color_value("ink"), w - 166, 4, 0)
        elif kind == "topic_line":
            _, (x, yy, w, h), idx, item = piece
            draw.rounded_rectangle((x, yy, x + w, yy + h), radius=18, fill=color_value("white"), outline=color_value("line"), width=2)
            draw.rounded_rectangle((x, yy, x + 14, yy + h), radius=6, fill=color_value("green"))
            draw.rounded_rectangle((x + 24, yy + 14, x + 50, yy + 40), radius=8, fill=color_value("soft_gold"), outline=color_value("gold"), width=1)
            draw.text((x + 37 - text_width(draw, str(idx), fonts["small_bold"]) // 2, yy + 15), f"{idx}", font=fonts["small_bold"], fill=color_value("gold_dark"))
            draw.text((x + 62, yy + 14), display_safe_text(item.get("topic") or ""), font=fonts["h3"], fill=color_value("ink"))
            draw.text((x + w - 130, yy + 20), f"出现 {item.get('count', 0)} 次", font=fonts["small_bold"], fill=color_value("muted"))
        elif kind == "timeline":
            _, (x, yy, w, h), item, topic = piece
            draw.rounded_rectangle((x, yy, x + w, yy + h), radius=18, fill=color_value("white"), outline=color_value("line"), width=2)
            draw.text((x + 20, yy + 20), display_safe_text(item.get("hour") or ""), font=fonts["h3"], fill=color_value("green"))
            draw.text((x + 126, yy + 16), display_safe_text(topic), font=fonts["body_bold"], fill=color_value("ink"))
            draw_wrapped(draw, (x + 126, yy + 50), item.get("text") or "", fonts["small_bold"], color_value("muted"), w - 238, 2, 0)
            draw.text((x + w - 86, yy + 34), f"{item.get('count', 0)} 条", font=fonts["small_bold"], fill=color_value("green_mid"))
        elif kind == "rank":
            _, (x, yy, w, h), idx, item = piece
            fill = "#fff7dc" if idx == 1 else "#f4f7f8" if idx == 2 else "#fff1e8" if idx == 3 else "#f9fcfb"
            outline = "gold" if idx == 1 else "silver" if idx == 2 else "bronze" if idx == 3 else "line"
            draw.rounded_rectangle((x, yy, x + w, yy + h), radius=20, fill=color_value(fill), outline=color_value(outline), width=4 if idx == 1 else 3 if idx <= 3 else 2)
            if idx == 1:
                draw.rounded_rectangle((x + 8, yy + 8, x + w - 8, yy + h - 8), radius=16, outline=color_value("gold_light"), width=2)
                draw.rectangle((x + 18, yy, x + w - 18, yy + 4), fill=color_value("gold_light"))
            medal_color = "gold" if idx == 1 else "silver" if idx == 2 else "bronze" if idx == 3 else "green"
            cx = x + 50
            cy = yy + h // 2
            if idx <= 3:
                draw_crown(draw, x + 20, yy - 12, 58, 32, color_value(medal_color), color_value("gold_light" if idx == 1 else medal_color))
            draw_avatar_frame(image, draw, cx, cy + (3 if idx <= 3 else 0), 28 if idx <= 3 else 22, idx, item.get("name") or "", fonts["avatar"], item.get("avatar_key") or item.get("username") or "")
            rank_badge = str(idx)
            draw.ellipse((x + 82, cy - 16, x + 114, cy + 16), fill=color_value(medal_color), outline=color_value("white"), width=2)
            draw.text((x + 98 - text_width(draw, rank_badge, fonts["small_bold"]) // 2, cy - 13), rank_badge, font=fonts["small_bold"], fill=color_value("white"))
            draw.text((x + 126, yy + (18 if idx <= 3 else 14)), display_safe_text(item.get("name") or ""), font=fonts["body_bold"], fill=color_value("ink"))
            if idx <= 3:
                label = "冠军水王 · 发言核心" if idx == 1 else "高能输出 · 话题推动"
                draw.text((x + 126, yy + 52), label, font=fonts["small"], fill=color_value("muted"))
            count = f"{item.get('count', 0)} 条"
            draw.text((x + w - text_width(draw, count, fonts["body_bold"]) - 22, yy + (24 if idx <= 3 else 12)), count, font=fonts["body_bold"], fill=color_value("green_mid"))

    image.save(output)


def chrome_path() -> str:
    candidates = [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        "google-chrome",
        "chromium",
    ]
    for item in candidates:
        path = Path(item)
        if path.exists():
            return str(path)
    return "google-chrome"


def render_png(html_text: str, output: Path) -> None:
    try:
        render_png_pillow(build_report_from_html_marker(html_text), output)
        return
    except Exception:
        pass
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        html_path = Path(tmp) / "report.html"
        html_path.write_text(html_text, encoding="utf-8")
        profile_dir = Path(tmp) / "chrome-profile"
        height_probe = [
            chrome_path(),
            "--headless=new",
            "--disable-gpu",
            "--disable-dev-shm-usage",
            "--no-first-run",
            "--no-default-browser-check",
            f"--user-data-dir={profile_dir}",
            "--dump-dom",
            html_path.as_uri(),
        ]
        # Chrome on macOS can keep updater helper processes around. The DOM dump
        # is only a warm-up; the final screenshot is considered successful once
        # the PNG exists.
        subprocess.run(height_probe, text=True, capture_output=True, timeout=20)
        command = [
            chrome_path(),
            "--headless=new",
            "--disable-gpu",
            "--disable-dev-shm-usage",
            "--no-first-run",
            "--no-default-browser-check",
            f"--user-data-dir={profile_dir}",
            "--hide-scrollbars",
            "--window-size=920,4200",
            f"--screenshot={output}",
            html_path.as_uri(),
        ]
        try:
            result = subprocess.run(command, text=True, capture_output=True, timeout=25)
        except subprocess.TimeoutExpired as exc:
            result = exc
        if not output.exists():
            if isinstance(result, subprocess.TimeoutExpired):
                raise RuntimeError(f"Chrome screenshot timed out before writing PNG: {result}") from result
            raise RuntimeError((result.stderr or result.stdout or "Chrome screenshot failed").strip())
    trim_png_bottom(output)


def build_report_from_html_marker(html_text: str) -> dict:
    marker = "<script id=\"wechatagent-report-data\" type=\"application/json\">"
    if marker not in html_text:
        raise ValueError("HTML does not contain report data marker")
    start = html_text.index(marker) + len(marker)
    end = html_text.index("</script>", start)
    return json.loads(html.unescape(html_text[start:end]))


def trim_png_bottom(path: Path) -> None:
    try:
        from PIL import Image
    except Exception:
        return
    image = Image.open(path).convert("RGB")
    width, height = image.size
    bg = image.getpixel((width // 2, height - 4))
    threshold = 12
    crop_y = height
    for y in range(height - 1, 0, -1):
        row_has_content = False
        for x in range(0, width, 12):
            pixel = image.getpixel((x, y))
            if sum(abs(pixel[i] - bg[i]) for i in range(3)) > threshold:
                row_has_content = True
                break
        if row_has_content:
            crop_y = min(height, y + 90)
            break
    if crop_y < height - 40:
        image.crop((0, 0, width, crop_y)).save(path)


def safe_slug(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_") or "report"


def generate_daily_report(
    chat_username: str,
    day: str = "",
    *,
    start_time: str | int | float | None = None,
    end_time: str | int | float | None = None,
    hours: int | float | None = None,
    llm_summary: dict | None = None,
    html_out: str | Path | None = None,
    png_out: str | Path | None = None,
    json_out: str | Path | None = None,
    no_png: bool = False,
) -> dict:
    report = build_report(
        chat_username,
        day,
        start_time=start_time,
        end_time=end_time,
        hours=hours,
        llm_summary=llm_summary,
    )
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    base = f"{safe_slug(report['chat_display'])}-{report['day']}"
    html_path = Path(html_out) if html_out else REPORT_DIR / f"{base}.html"
    png_path = Path(png_out) if png_out else REPORT_DIR / f"{base}.png"
    json_path = Path(json_out) if json_out else REPORT_DIR / f"{base}.json"
    html_text = render_html(report)
    html_path.write_text(html_text, encoding="utf-8")
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if not no_png:
        render_png_pillow(report, png_path)
    return {
        "ok": True,
        "html": str(html_path),
        "png": "" if no_png else str(png_path),
        "json": str(json_path),
        "report": report,
        "stats": report["stats"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--chat", required=True)
    parser.add_argument("--day", default="")
    parser.add_argument("--start-time", default="")
    parser.add_argument("--end-time", default="")
    parser.add_argument("--hours", type=float, default=0)
    parser.add_argument("--llm-summary-json", default="")
    parser.add_argument("--html-out", default="")
    parser.add_argument("--png-out", default="")
    parser.add_argument("--json-out", default="")
    parser.add_argument("--no-png", action="store_true")
    args = parser.parse_args()
    llm_summary = {}
    if args.llm_summary_json:
        llm_summary = json.loads(Path(args.llm_summary_json).read_text(encoding="utf-8"))

    result = generate_daily_report(
        args.chat,
        args.day,
        start_time=args.start_time or None,
        end_time=args.end_time or None,
        hours=args.hours or None,
        llm_summary=llm_summary,
        html_out=args.html_out or None,
        png_out=args.png_out or None,
        json_out=args.json_out or None,
        no_png=args.no_png,
    )
    result.pop("report", None)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
