#!/usr/bin/env python3
"""Small X11 controller for the Linux WeChat window.

This script intentionally does not inspect screenshots or write WeChat databases.
It drives the main Linux WeChat window through X11 and closes embedded web
windows that would otherwise steal focus.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import struct
import subprocess
import sys
import time


DISPLAY = ":1"


def run(args: list[str], input_text: str | None = None, check: bool = True) -> subprocess.CompletedProcess:
    env = None
    full_args = args
    if args and args[0] in {"xdotool", "xclip", "xprop", "xwd"}:
        env = {**os.environ, "DISPLAY": DISPLAY}
    result = subprocess.run(
        full_args,
        input=input_text,
        text=True,
        capture_output=True,
        env=env,
    )
    if check and result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or f"{args[0]} failed").strip())
    return result


def b64_decode(value: str) -> str:
    if not value:
        return ""
    return base64.b64decode(value.encode("ascii")).decode("utf-8")


def xdotool(*args: str, check: bool = True) -> str:
    result = run(["xdotool", *args], check=check)
    return result.stdout.strip()


def xprop(window_id: str) -> str:
    return run(["xprop", "-id", window_id, "WM_CLASS", "_NET_WM_NAME", "WM_NAME"], check=False).stdout


def mask_shift(mask: int) -> int:
    shift = 0
    while mask and not mask & 1:
        shift += 1
        mask >>= 1
    return shift


def mask_to_255(raw: int, mask: int) -> int:
    if not mask:
        return 0
    value = (raw & mask) >> mask_shift(mask)
    maximum = mask >> mask_shift(mask)
    if maximum <= 0:
        return 0
    return int(round(value * 255 / maximum))


def read_window_xwd(window_id: str) -> bytes:
    path = f"/tmp/wechat-window-status-{os.getpid()}-{int(time.time() * 1000)}.xwd"
    try:
        run(["xwd", "-silent", "-id", str(window_id), "-out", path])
        with open(path, "rb") as handle:
            return handle.read()
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def parse_xwd(data: bytes) -> dict:
    if len(data) < 100:
        raise RuntimeError("XWD 截图数据过短")
    header = struct.unpack(">25I", data[:100])
    (
        header_size,
        version,
        _pixmap_format,
        _pixmap_depth,
        width,
        height,
        _xoffset,
        _byte_order,
        _bitmap_unit,
        _bitmap_bit_order,
        _bitmap_pad,
        bits_per_pixel,
        bytes_per_line,
        _visual_class,
        red_mask,
        green_mask,
        blue_mask,
        _bits_per_rgb,
        _colormap_entries,
        ncolors,
        *_rest,
    ) = header
    if version != 7 or width <= 0 or height <= 0 or width > 10_000 or height > 10_000:
        raise RuntimeError("XWD 截图头格式异常")
    if header_size < 100 or bytes_per_line <= 0:
        raise RuntimeError("XWD 截图尺寸异常")
    pixel_offset = header_size + ncolors * 12
    required = pixel_offset + bytes_per_line * height
    if len(data) < required:
        raise RuntimeError("XWD 截图像素数据不完整")
    bytes_per_pixel = max(1, min(8, bytes_per_line // max(width, 1)))
    if bits_per_pixel in {16, 24, 32}:
        bytes_per_pixel = max(bytes_per_pixel, 4 if bits_per_pixel == 24 and bytes_per_line >= width * 4 else bits_per_pixel // 8)
    return {
        "data": data,
        "width": width,
        "height": height,
        "bytes_per_line": bytes_per_line,
        "bytes_per_pixel": bytes_per_pixel,
        "pixel_offset": pixel_offset,
        "red_mask": red_mask,
        "green_mask": green_mask,
        "blue_mask": blue_mask,
    }


def xwd_rgb(image: dict, x: int, y: int, byteorder: str = "big") -> tuple[int, int, int]:
    offset = int(image["pixel_offset"]) + y * int(image["bytes_per_line"]) + x * int(image["bytes_per_pixel"])
    chunk = image["data"][offset : offset + int(image["bytes_per_pixel"])]
    raw = int.from_bytes(chunk, byteorder=byteorder, signed=False)
    return (
        mask_to_255(raw, int(image["red_mask"])),
        mask_to_255(raw, int(image["green_mask"])),
        mask_to_255(raw, int(image["blue_mask"])),
    )


def region_color_metrics(image: dict, box: tuple[float, float, float, float], byteorder: str = "big") -> dict:
    width = int(image["width"])
    height = int(image["height"])
    left = max(0, min(width - 1, int(width * box[0])))
    top = max(0, min(height - 1, int(height * box[1])))
    right = max(left + 1, min(width, int(width * box[2])))
    bottom = max(top + 1, min(height, int(height * box[3])))
    step = max(1, min(right - left, bottom - top) // 28)
    total = 0
    green = 0
    bright = 0
    dark = 0
    red_sum = green_sum = blue_sum = sat_sum = 0.0
    for y in range(top, bottom, step):
        for x in range(left, right, step):
            r, g, b = xwd_rgb(image, x, y, byteorder=byteorder)
            total += 1
            red_sum += r
            green_sum += g
            blue_sum += b
            high = max(r, g, b)
            low = min(r, g, b)
            saturation = 0.0 if high <= 0 else (high - low) / high
            sat_sum += saturation
            if g >= 110 and g > r * 1.18 and g > b * 1.18 and saturation >= 0.32:
                green += 1
            if r >= 220 and g >= 220 and b >= 220:
                bright += 1
            if high <= 105:
                dark += 1
    total = max(total, 1)
    return {
        "box": [left, top, right, bottom],
        "byteorder": byteorder,
        "samples": total,
        "green_ratio": round(green / total, 3),
        "bright_ratio": round(bright / total, 3),
        "dark_ratio": round(dark / total, 3),
        "avg_rgb": [round(red_sum / total, 1), round(green_sum / total, 1), round(blue_sum / total, 1)],
        "avg_saturation": round(sat_sum / total, 3),
    }


def green_pixel_signal(rgb: tuple[int, int, int]) -> bool:
    r, g, b = rgb
    high = max(r, g, b)
    low = min(r, g, b)
    saturation = 0.0 if high <= 0 else (high - low) / high
    return bool(g >= 110 and g > r * 1.18 and g > b * 1.18 and saturation >= 0.32)


def point_color_signal(image: dict, rel_x: float, rel_y: float) -> dict:
    width = int(image["width"])
    height = int(image["height"])
    x = max(0, min(width - 1, int(width * rel_x)))
    y = max(0, min(height - 1, int(height * rel_y)))
    big = xwd_rgb(image, x, y, "big")
    little = xwd_rgb(image, x, y, "little")
    chosen = big if green_pixel_signal(big) or sum(big) <= sum(little) else little
    return {
        "point": [x, y],
        "rgb_big": list(big),
        "rgb_little": list(little),
        "green": bool(green_pixel_signal(big) or green_pixel_signal(little)),
    }


def window_visual_status(window: dict) -> dict:
    image = parse_xwd(read_window_xwd(str(window["window_id"])))
    login_region_box = (0.12, 0.72, 0.65, 0.82)
    metrics_big = region_color_metrics(image, login_region_box, "big")
    metrics_little = region_color_metrics(image, login_region_box, "little")
    login_button = max([metrics_big, metrics_little], key=lambda item: float(item.get("green_ratio") or 0.0))
    login_center = point_color_signal(image, 0.50, 0.77)
    left_nav_big = region_color_metrics(image, (0.00, 0.08, 0.20, 0.98), "big")
    left_nav_little = region_color_metrics(image, (0.00, 0.08, 0.20, 0.98), "little")
    left_nav = max([left_nav_big, left_nav_little], key=lambda item: float(item.get("dark_ratio") or 0.0))
    width = int(window.get("width") or image["width"] or 0)
    height = int(window.get("height") or image["height"] or 0)
    green_ratio = float(login_button.get("green_ratio") or 0.0)
    avg_rgb = login_button.get("avg_rgb") or [0, 0, 0]
    has_chat_sidebar = float(left_nav.get("dark_ratio") or 0.0) >= 0.20
    login_required = (
        240 <= width <= 380
        and 320 <= height <= 520
        and (
            bool(login_center.get("green"))
            or (
                green_ratio >= 0.18
                and float(avg_rgb[1]) >= float(avg_rgb[0]) + 8
                and float(avg_rgb[1]) >= float(avg_rgb[2]) + 8
            )
        )
    )
    if login_required:
        ui_state = "login_required"
    elif has_chat_sidebar:
        ui_state = "chat"
    elif 240 <= width <= 380 and 320 <= height <= 520:
        ui_state = "login_pending"
    else:
        ui_state = "unknown"
    return {
        "ui_state": ui_state,
        "login_required": bool(login_required),
        "signals": {
            "screenshot_width": int(image["width"]),
            "screenshot_height": int(image["height"]),
            "login_button": login_button,
            "login_center": login_center,
            "left_nav": left_nav,
        },
    }


def window_geometry(window_id: str) -> dict:
    output = xdotool("getwindowgeometry", "--shell", window_id)
    parsed: dict[str, int | str] = {"window_id": window_id}
    for line in output.splitlines():
        if "=" not in line:
            continue
        key, raw = line.split("=", 1)
        try:
            parsed[key.lower()] = int(raw)
        except ValueError:
            parsed[key.lower()] = raw
    return parsed


def window_name(window_id: str) -> str:
    return xdotool("getwindowname", window_id, check=False).strip()


def close_non_main_wechat_windows() -> None:
    result = run(["xdotool", "search", "--onlyvisible", "--name", "微信"], check=False)
    for window_id in result.stdout.splitlines():
        window_id = window_id.strip()
        if not window_id:
            continue
        try:
            geom = window_geometry(window_id)
            props = xprop(window_id)
        except Exception:
            continue
        width = int(geom.get("width") or 0)
        height = int(geom.get("height") or 0)
        if width * height < 20_000:
            continue
        if "wechat" in props:
            continue
        xdotool("windowclose", window_id, check=False)
        sleep_seconds(0.2)


def find_main_window() -> dict:
    close_non_main_wechat_windows()
    result = run(["xdotool", "search", "--onlyvisible", "--class", "wechat"], check=False)
    candidates: list[dict] = []
    for window_id in result.stdout.splitlines():
        if not window_id.strip():
            continue
        geom = window_geometry(window_id.strip())
        width = int(geom.get("width") or 0)
        height = int(geom.get("height") or 0)
        name = window_name(window_id.strip())
        props = xprop(window_id.strip())
        if name != "微信" or width < 240 or height < 320 or "wechat" not in props:
            continue
        geom["name"] = name
        geom["area"] = width * height
        candidates.append(geom)
    if not candidates:
        raise RuntimeError("未找到可控制的微信主聊天窗口")
    return max(candidates, key=lambda item: int(item.get("area") or 0))


def sleep_seconds(seconds: float) -> None:
    if seconds > 0:
        time.sleep(seconds)


def start_clipboard(text: str) -> subprocess.Popen:
    proc = subprocess.Popen(
        ["xclip", "-selection", "clipboard", "-loops", "8"],
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        env={**os.environ, "DISPLAY": DISPLAY},
    )
    assert proc.stdin is not None
    proc.stdin.write(text)
    proc.stdin.close()
    return proc


def start_image_clipboard(path: str) -> subprocess.Popen:
    if not os.path.exists(path):
        raise RuntimeError(f"图片文件不存在: {path}")
    mime = "image/png" if path.lower().endswith(".png") else "image/jpeg"
    proc = subprocess.Popen(
        ["xclip", "-selection", "clipboard", "-target", mime, "-loops", "8", "-i", path],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        env={**os.environ, "DISPLAY": DISPLAY},
    )
    return proc


def finish_clipboard(proc: subprocess.Popen) -> None:
    try:
        proc.wait(timeout=0.6)
    except subprocess.TimeoutExpired:
        proc.terminate()
        try:
            proc.wait(timeout=1)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=1)
        return
    if proc.returncode not in (0, None):
        stderr = ""
        if proc.stderr:
            try:
                stderr = proc.stderr.read()
            except Exception:
                stderr = ""
        raise RuntimeError((stderr or "剪贴板写入失败").strip())


def paste_text(text: str) -> None:
    proc = start_clipboard(text)
    sleep_seconds(0.12)
    key("ctrl+v")
    sleep_seconds(0.35)
    finish_clipboard(proc)


def type_text(text: str, delay_ms: int = 18) -> None:
    if not text:
        return
    xdotool("type", "--clearmodifiers", "--delay", str(max(0, delay_ms)), text)
    sleep_seconds(0.12)


def paste_image(path: str) -> None:
    proc = start_image_clipboard(path)
    sleep_seconds(0.18)
    key("ctrl+v")
    sleep_seconds(0.6)
    finish_clipboard(proc)


def read_clipboard_text() -> str:
    try:
        result = subprocess.run(
            ["xclip", "-selection", "clipboard", "-o"],
            text=True,
            capture_output=True,
            timeout=2,
            env={**os.environ, "DISPLAY": DISPLAY},
        )
    except subprocess.TimeoutExpired:
        return ""
    return result.stdout if result.returncode == 0 else ""


def verify_focused_text(expected: str) -> dict:
    key("ctrl+a")
    sleep_seconds(0.08)
    key("ctrl+c")
    sleep_seconds(0.18)
    copied = read_clipboard_text()
    key("Right")
    return {
        "ok": copied == expected,
        "copied_length": len(copied),
        "expected_length": len(expected),
        "copied_preview": copied[:80],
    }


def verify_mention_text(display_name: str, alias: str, body: str) -> dict:
    key("ctrl+a")
    sleep_seconds(0.08)
    key("ctrl+c")
    sleep_seconds(0.18)
    copied = read_clipboard_text()
    key("Right")
    compact = copied.replace("\u2005", " ").replace("\u2004", " ").strip()
    display = display_name.strip()
    alias_text = alias.strip().lstrip("@")
    body_text = body.strip()
    has_body = bool(body_text and body_text in compact)
    has_display_mention = bool(display and f"@{display}" in compact)
    has_raw_alias = bool(alias_text and f"@{alias_text}" in compact)
    return {
        "ok": bool(has_body and has_display_mention and not has_raw_alias),
        "copied_length": len(copied),
        "copied_preview": copied[:120],
        "has_body": has_body,
        "has_display_mention": has_display_mention,
        "has_raw_alias": has_raw_alias,
        "expected_display": display,
        "alias": alias_text,
    }


def click(window: dict, rel_x: int, rel_y: int) -> None:
    x = int(window["x"]) + int(rel_x)
    y = int(window["y"]) + int(rel_y)
    xdotool("mousemove", str(x), str(y), "click", "1")


def key(*keys: str) -> None:
    xdotool("key", *keys)


def activate(window: dict) -> None:
    xdotool("windowactivate", "--sync", str(window["window_id"]))
    xdotool("windowraise", str(window["window_id"]), check=False)
    sleep_seconds(0.15)


def chat_tab_point(window: dict) -> tuple[int, int]:
    width = int(window.get("width") or 0)
    if width <= 360:
        return 28, 92
    return 31, 104


def search_box_point(window: dict) -> tuple[int, int]:
    width = int(window.get("width") or 0)
    if width <= 360:
        return max(70, int(width * 0.42)), 42
    return 115, 42


def clear_focused_text() -> None:
    key("ctrl+a")
    sleep_seconds(0.05)
    key("BackSpace")
    sleep_seconds(0.08)


def chat_search_query(chat_name: str) -> str:
    compact = chat_name.strip()
    lowered = compact.lower()
    if "pt站看片狂魔小群" in lowered or lowered.startswith("pt"):
        return "PT"
    if "值班群" in compact or compact.startswith("值班"):
        return "值班"
    return compact


def open_chat(chat_name: str, switch_delay: float) -> dict:
    chat_name = chat_name.strip()
    if not chat_name:
        raise RuntimeError("缺少目标群名")
    search_query = chat_search_query(chat_name)
    window = find_main_window()
    activate(window)
    width = int(window["width"])
    height = int(window["height"])

    key("Escape")
    sleep_seconds(0.08)
    click(window, *chat_tab_point(window))
    sleep_seconds(0.15)

    click(window, *search_box_point(window))
    sleep_seconds(0.1)
    clear_focused_text()
    paste_text(search_query)
    sleep_seconds(0.55)

    # Short local queries ("PT", "值班") highlight the exact recent chat. Full
    # names can trigger WeChat's global search page instead.
    key("Return")
    sleep_seconds(max(switch_delay, 0.2))
    return {
        "window": window,
        "chat_name": chat_name,
        "search_query": search_query,
        "switch_delay_seconds": switch_delay,
        "width": width,
        "height": height,
    }


def paste_active(text: str, send: bool, send_delay: float) -> dict:
    if not text.strip():
        raise RuntimeError("回复内容为空")
    window = find_main_window()
    activate(window)
    width = int(window["width"])
    height = int(window["height"])
    input_x = max(80, int(width * 0.57))
    input_y = max(120, height - 70)
    click(window, input_x, input_y)
    sleep_seconds(0.12)
    clear_focused_text()
    paste_text(text)
    sleep_seconds(0.15)
    input_verify = verify_focused_text(text)
    if not input_verify.get("ok"):
        raise RuntimeError("微信输入框内容校验失败，粘贴内容未出现在当前输入框")
    if send:
        sleep_seconds(max(send_delay, 0))
        key("Return")
    return {
        "window": window,
        "sent": bool(send),
        "send_delay_seconds": send_delay if send else 0,
        "input": {"x": input_x, "y": input_y},
        "input_verify": input_verify,
    }


def strip_plain_mention_prefix(text: str, display_name: str) -> str:
    body = text.strip()
    name = display_name.strip()
    if name and body.startswith(f"@{name}"):
        body = body[len(name) + 1 :].lstrip(" \t\r\n:：,，")
    return body


def paste_mention_active(text: str, mention_alias: str, mention_display: str, send: bool, send_delay: float) -> dict:
    body = strip_plain_mention_prefix(text, mention_display)
    if not body:
        raise RuntimeError("回复内容为空")
    alias = mention_alias.strip().lstrip("@")
    if not alias:
        raise RuntimeError("缺少可用于蓝色@的 alias")
    window = find_main_window()
    activate(window)
    width = int(window["width"])
    height = int(window["height"])
    input_x = max(80, int(width * 0.57))
    input_y = max(120, height - 70)
    click(window, input_x, input_y)
    sleep_seconds(0.12)
    clear_focused_text()

    type_text("@", delay_ms=20)
    sleep_seconds(0.45)
    type_text(alias, delay_ms=22)
    sleep_seconds(0.65)
    key("Return")
    sleep_seconds(0.45)
    paste_text(f" {body}")
    sleep_seconds(0.15)
    input_verify = verify_mention_text(mention_display, alias, body)
    if not input_verify.get("ok"):
        clear_focused_text()
        raise RuntimeError("微信蓝色@校验失败，已清空输入框，拒绝发送裸 alias")

    if send:
        sleep_seconds(max(send_delay, 0))
        key("Return")
    return {
        "window": window,
        "sent": bool(send),
        "send_delay_seconds": send_delay if send else 0,
        "input": {"x": input_x, "y": input_y},
        "mention": {
            "alias": alias,
            "display": mention_display,
            "body_length": len(body),
            "strategy": "type_alias_tab_then_body",
        },
        "input_verify": input_verify,
    }


def paste_image_active(path: str, send: bool, send_delay: float) -> dict:
    if not os.path.exists(path):
        raise RuntimeError(f"图片文件不存在: {path}")
    window = find_main_window()
    activate(window)
    width = int(window["width"])
    height = int(window["height"])
    input_x = max(80, int(width * 0.57))
    input_y = max(120, height - 70)
    click(window, input_x, input_y)
    sleep_seconds(0.12)
    clear_focused_text()
    paste_image(path)
    if send:
        sleep_seconds(max(send_delay, 0))
        key("Return")
    return {
        "window": window,
        "sent": bool(send),
        "send_delay_seconds": send_delay if send else 0,
        "input": {"x": input_x, "y": input_y},
        "image_path": path,
    }


def submit_active(send_delay: float) -> dict:
    window = find_main_window()
    activate(window)
    sleep_seconds(max(send_delay, 0))
    key("Return")
    return {"window": window, "sent": True, "send_delay_seconds": send_delay}


def focus_active() -> dict:
    window = find_main_window()
    activate(window)
    return {"window": window, "focused": True}


def window_status() -> dict:
    window = find_main_window()
    status = {"window": window, "available": True}
    try:
        status.update(window_visual_status(window))
    except Exception as exc:
        status.update({"ui_state": "unknown", "login_required": False, "visual_error": str(exc)})
    return status


def clear_active() -> dict:
    window = find_main_window()
    activate(window)
    width = int(window["width"])
    height = int(window["height"])
    click(window, max(80, int(width * 0.57)), max(120, height - 70))
    sleep_seconds(0.1)
    clear_focused_text()
    return {"window": window, "cleared": True}


def login_guard_click(ack_ratio_y: float = 0.60, login_ratio_y: float = 0.77) -> dict:
    window = find_main_window()
    activate(window)
    width = int(window["width"])
    height = int(window["height"])
    center_x = max(30, width // 2)
    clicked = []
    before_status = {}
    after_status = {}
    try:
        before_status = window_visual_status(window)
    except Exception as exc:
        before_status = {"ui_state": "unknown", "visual_error": str(exc)}

    click(window, center_x, max(40, int(height * ack_ratio_y)))
    sleep_seconds(0.9)
    clicked.append({"target": "ack", "x": center_x, "y": int(height * ack_ratio_y)})

    click(window, center_x, max(40, int(height * login_ratio_y)))
    sleep_seconds(0.8)
    clicked.append({"target": "login", "x": center_x, "y": int(height * login_ratio_y)})
    try:
        after_status = window_visual_status(window)
    except Exception as exc:
        after_status = {"ui_state": "unknown", "visual_error": str(exc)}

    return {
        "window": window,
        "clicked": clicked,
        "ack_ratio_y": ack_ratio_y,
        "login_ratio_y": login_ratio_y,
        "before_status": before_status,
        "after_status": after_status,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "action",
        choices=["open", "paste", "mention-paste", "image", "submit", "focus", "status", "clear", "login-guard-click"],
    )
    parser.add_argument("--chat-name-b64", default="")
    parser.add_argument("--text-b64", default="")
    parser.add_argument("--mention-alias-b64", default="")
    parser.add_argument("--mention-display-b64", default="")
    parser.add_argument("--image-path-b64", default="")
    parser.add_argument("--send", action="store_true")
    parser.add_argument("--switch-delay", type=float, default=1.0)
    parser.add_argument("--send-delay", type=float, default=0.0)
    parser.add_argument("--ack-ratio-y", type=float, default=0.60)
    parser.add_argument("--login-ratio-y", type=float, default=0.77)
    args = parser.parse_args()
    try:
        if args.action == "open":
            payload = open_chat(b64_decode(args.chat_name_b64), args.switch_delay)
        elif args.action == "paste":
            payload = paste_active(b64_decode(args.text_b64), args.send, args.send_delay)
        elif args.action == "mention-paste":
            payload = paste_mention_active(
                b64_decode(args.text_b64),
                b64_decode(args.mention_alias_b64),
                b64_decode(args.mention_display_b64),
                args.send,
                args.send_delay,
            )
        elif args.action == "image":
            payload = paste_image_active(b64_decode(args.image_path_b64), args.send, args.send_delay)
        elif args.action == "submit":
            payload = submit_active(args.send_delay)
        elif args.action == "focus":
            payload = focus_active()
        elif args.action == "status":
            payload = window_status()
        elif args.action == "login-guard-click":
            payload = login_guard_click(args.ack_ratio_y, args.login_ratio_y)
        else:
            payload = clear_active()
        print(json.dumps({"ok": True, **payload}, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
