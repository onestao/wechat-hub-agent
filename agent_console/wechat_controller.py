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
import subprocess
import sys
import time


DISPLAY = ":1"


def run(args: list[str], input_text: str | None = None, check: bool = True) -> subprocess.CompletedProcess:
    env = None
    full_args = args
    if args and args[0] in {"xdotool", "xclip", "xprop"}:
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


def submit_active(send_delay: float) -> dict:
    window = find_main_window()
    activate(window)
    sleep_seconds(max(send_delay, 0))
    key("Return")
    return {"window": window, "sent": True, "send_delay_seconds": send_delay}


def clear_active() -> dict:
    window = find_main_window()
    activate(window)
    width = int(window["width"])
    height = int(window["height"])
    click(window, max(80, int(width * 0.57)), max(120, height - 70))
    sleep_seconds(0.1)
    clear_focused_text()
    return {"window": window, "cleared": True}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["open", "paste", "submit", "clear"])
    parser.add_argument("--chat-name-b64", default="")
    parser.add_argument("--text-b64", default="")
    parser.add_argument("--send", action="store_true")
    parser.add_argument("--switch-delay", type=float, default=1.0)
    parser.add_argument("--send-delay", type=float, default=0.0)
    args = parser.parse_args()
    try:
        if args.action == "open":
            payload = open_chat(b64_decode(args.chat_name_b64), args.switch_delay)
        elif args.action == "paste":
            payload = paste_active(b64_decode(args.text_b64), args.send, args.send_delay)
        elif args.action == "submit":
            payload = submit_active(args.send_delay)
        else:
            payload = clear_active()
        print(json.dumps({"ok": True, **payload}, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
