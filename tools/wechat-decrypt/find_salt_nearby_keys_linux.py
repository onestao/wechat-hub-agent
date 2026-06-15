"""
Linux WeChat 4.x fallback key scan.

Some builds do not keep WCDB keys as the text pattern x'<hexkey><salt>'.
This diagnostic scanner searches for each database salt in process memory and
tries nearby 32-byte values as SQLCipher raw keys, verifying candidates against
page 1 HMAC. It intentionally never prints raw key material.
"""

import functools
import os
import re
import sys
import time

from config import load_config
from find_all_keys_linux import get_pids
from key_scan_common import collect_db_files, cross_verify_keys, save_results, verify_enc_key

print = functools.partial(print, flush=True)

CHUNK_SIZE = 8 * 1024 * 1024
OVERLAP = 8192
NEARBY_WINDOW = 4096
MAX_REGION_SIZE = 2 * 1024 * 1024 * 1024


def _readable_regions(pid):
    regions = []
    with open(f"/proc/{pid}/maps") as f:
        for line in f:
            parts = line.split()
            if len(parts) < 2 or "r" not in parts[1]:
                continue
            start_s, end_s = parts[0].split("-")
            start = int(start_s, 16)
            end = int(end_s, 16)
            size = end - start
            if size <= 0 or size > MAX_REGION_SIZE:
                continue
            name = parts[5] if len(parts) >= 6 else ""
            regions.append((start, size, name))
    return regions


def _entropy_ok(buf):
    if len(buf) != 32:
        return False
    if buf == b"\x00" * 32 or buf == b"\xff" * 32:
        return False
    return len(set(buf)) >= 8


def _try_key(salt_hex, key_bytes, salt_to_dbs, db_by_rel, key_map, tried, pid, addr, source):
    if salt_hex in key_map or not _entropy_ok(key_bytes):
        return False
    key_hex = key_bytes.hex()
    tried_for_salt = tried.setdefault(salt_hex, set())
    if key_hex in tried_for_salt:
        return False
    tried_for_salt.add(key_hex)

    for rel in salt_to_dbs[salt_hex]:
        page1 = db_by_rel[rel][4]
        if verify_enc_key(key_bytes, page1):
            key_map[salt_hex] = key_hex
            print(f"\n  [FOUND] salt={salt_hex}")
            print("    enc_key=<redacted>")
            print(f"    PID={pid} 地址: 0x{addr:016X} 来源: {source}")
            print(f"    数据库: {', '.join(salt_to_dbs[salt_hex])}")
            return True
    return False


def _iter_matches(data, needle):
    start = 0
    while True:
        idx = data.find(needle, start)
        if idx < 0:
            return
        yield idx
        start = idx + 1


def _try_binary_nearby(data, match_idx, base_addr, salt_hex, salt_to_dbs, db_by_rel, key_map, tried, pid):
    start = max(0, match_idx - NEARBY_WINDOW)
    end = min(len(data), match_idx + 16 + NEARBY_WINDOW)

    priority_offsets = []
    for delta in (-128, -96, -80, -64, -48, -40, -32, -24, -16, 16, 24, 32, 40, 48, 64, 80, 96, 128):
        priority_offsets.append(match_idx + delta)
    for off in priority_offsets:
        if 0 <= off <= len(data) - 32:
            if _try_key(
                salt_hex, data[off : off + 32], salt_to_dbs, db_by_rel, key_map, tried,
                pid, base_addr + off, f"binary-near-salt[{off - match_idx:+d}]",
            ):
                return True

    for off in range(start, end - 31):
        if _try_key(
            salt_hex, data[off : off + 32], salt_to_dbs, db_by_rel, key_map, tried,
            pid, base_addr + off, "binary-window",
        ):
            return True
    return False


_HEX_RE = re.compile(rb"[0-9a-fA-F]{64,256}")


def _try_ascii_hex_nearby(data, match_idx, base_addr, salt_hex, salt_to_dbs, db_by_rel, key_map, tried, pid):
    start = max(0, match_idx - 512)
    end = min(len(data), match_idx + 32 + 512)
    window = data[start:end]
    salt_ascii = salt_hex.encode("ascii")

    for m in _HEX_RE.finditer(window):
        token = m.group(0)
        pos = token.lower().find(salt_ascii)
        if pos < 0:
            continue
        candidates = []
        if pos >= 64:
            candidates.append(token[pos - 64 : pos])
        if len(token) >= pos + 32 + 64:
            candidates.append(token[pos + 32 : pos + 32 + 64])
        if len(token) >= 64:
            candidates.append(token[:64])
            candidates.append(token[-64:])
        for cand in candidates:
            try:
                key_bytes = bytes.fromhex(cand.decode("ascii"))
            except ValueError:
                continue
            addr = base_addr + start + m.start()
            if _try_key(salt_hex, key_bytes, salt_to_dbs, db_by_rel, key_map, tried, pid, addr, "ascii-hex"):
                return True
    return False


def _scan_region(pid, mem, start, size, name, salt_needles, salt_to_dbs, db_by_rel, key_map, tried):
    offset = 0
    carry = b""
    salt_hits = 0
    while offset < size:
        to_read = min(CHUNK_SIZE, size - offset)
        try:
            mem.seek(start + offset)
            chunk = mem.read(to_read)
        except (OSError, ValueError):
            return salt_hits
        if not chunk:
            return salt_hits
        data = carry + chunk
        data_base = start + offset - len(carry)

        for salt_hex, raw_salt, ascii_salt in salt_needles:
            if salt_hex in key_map:
                continue
            for idx in _iter_matches(data, raw_salt):
                salt_hits += 1
                if _try_binary_nearby(data, idx, data_base, salt_hex, salt_to_dbs, db_by_rel, key_map, tried, pid):
                    break
            if salt_hex in key_map:
                continue
            for idx in _iter_matches(data.lower(), ascii_salt):
                salt_hits += 1
                if _try_ascii_hex_nearby(data, idx, data_base, salt_hex, salt_to_dbs, db_by_rel, key_map, tried, pid):
                    break

        carry = data[-OVERLAP:] if len(data) > OVERLAP else data
        offset += to_read
    return salt_hits


def main():
    cfg = load_config()
    db_dir = cfg["db_dir"]
    out_file = cfg["keys_file"]

    db_files, salt_to_dbs = collect_db_files(db_dir)
    if not db_files:
        raise RuntimeError(f"在 {db_dir} 未找到可解密的 .db 文件")

    print("=" * 60)
    print("  Linux 微信数据库密钥备用扫描（salt 附近候选）")
    print("=" * 60)
    print(f"找到 {len(db_files)} 个数据库, {len(salt_to_dbs)} 个不同的 salt")

    db_by_rel = {rel: item for item in db_files for rel in [item[0]]}
    salt_needles = [
        (salt_hex, bytes.fromhex(salt_hex), salt_hex.encode("ascii"))
        for salt_hex in salt_to_dbs
    ]
    key_map = {}
    tried = {}
    total_hits = 0
    t0 = time.time()

    for pid, rss_kb in get_pids():
        try:
            regions = _readable_regions(pid)
            mem = open(f"/proc/{pid}/mem", "rb")
        except (PermissionError, FileNotFoundError, ProcessLookupError):
            continue

        total_mb = sum(size for _, size, _ in regions) / 1024 / 1024
        print(f"\n[*] 扫描 PID={pid} ({total_mb:.0f}MB, {len(regions)} 区域)")
        try:
            for idx, (start, size, name) in enumerate(regions, 1):
                total_hits += _scan_region(
                    pid, mem, start, size, name,
                    salt_needles, salt_to_dbs, db_by_rel, key_map, tried,
                )
                if idx % 200 == 0:
                    print(f"  区域 {idx}/{len(regions)} salt_hits={total_hits} keys={len(key_map)}/{len(salt_to_dbs)}")
                if len(key_map) == len(salt_to_dbs):
                    break
        finally:
            mem.close()
        if len(key_map) == len(salt_to_dbs):
            break

    print(f"\n扫描完成: {time.time() - t0:.1f}s, salt_hits={total_hits}, keys={len(key_map)}/{len(salt_to_dbs)}")
    cross_verify_keys(db_files, salt_to_dbs, key_map, print)
    save_results(db_files, salt_to_dbs, key_map, db_dir, out_file, print)
    try:
        os.chmod(out_file, 0o600)
    except OSError:
        pass


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as exc:
        print(f"\n[ERROR] {exc}")
        sys.exit(1)
