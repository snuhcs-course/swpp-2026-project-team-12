"""Fetch only selected entries of the pinned public Git LFS ZIP using ranges."""
from __future__ import annotations

import concurrent.futures
import hashlib
import json
import os
import struct
import tempfile
import threading
import time
import urllib.error
import urllib.request
import zlib
from pathlib import Path

from .common import ROOT, image_destination, manifest, save, sha


def valid_file(path, row):
    return path.is_file() and path.stat().st_size == row["size_bytes"] and sha(path) == row["sha256"]


class RangeSource:
    def __init__(self, source):
        self.source = source
        self.action = None
        self.lock = threading.Lock()
        self.bytes_received = 0

    def transport(self, refresh=False):
        # Signed transport URLs are acquired at runtime and never saved.
        with self.lock:
            if self.action is None or refresh:
                body = json.dumps({"operation": "download", "transfers": ["basic"], "objects": [
                    {"oid": self.source["archive_sha256"], "size": self.source["archive_size"]}
                ]}).encode()
                req = urllib.request.Request(self.source["lfs_batch_url"], data=body, headers={
                    "Content-Type": "application/vnd.git-lfs+json", "Accept": "application/vnd.git-lfs+json",
                    "User-Agent": "Todak-MemoryQA-Reproduction/1"})
                with urllib.request.urlopen(req, timeout=45) as response:
                    obj = json.load(response)["objects"][0]
                if obj.get("oid") != self.source["archive_sha256"] or obj.get("size") != self.source["archive_size"]:
                    raise RuntimeError("LFS object does not match the pinned archive")
                self.action = obj["actions"]["download"]
            return dict(self.action)

    def fetch(self, start, length):
        if start < 0 or length <= 0 or start + length > self.source["archive_size"]:
            raise ValueError("Range outside the pinned archive")
        end = start + length - 1
        for attempt in range(3):
            try:
                action = self.transport()
                req = urllib.request.Request(action["href"], headers={**action.get("header", {}),
                    "Range": f"bytes={start}-{end}", "User-Agent": "Todak-MemoryQA-Reproduction/1"})
                with urllib.request.urlopen(req, timeout=90) as response:
                    expected = f"bytes {start}-{end}/{self.source['archive_size']}"
                    if response.status != 206 or response.headers.get("Content-Range") != expected:
                        raise RuntimeError("Server ignored Range; full archive download refused")
                    data = response.read(length + 1)
                if len(data) != length:
                    raise RuntimeError("Truncated or oversized range response")
                with self.lock:
                    self.bytes_received += len(data)
                return data
            except (urllib.error.URLError, TimeoutError, OSError) as error:
                if attempt == 2:
                    raise RuntimeError("Public image download failed; rerun to resume") from None
                if isinstance(error, urllib.error.HTTPError):
                    self.transport(refresh=True)
                time.sleep(1 + attempt)
        raise RuntimeError("Unreachable")


def unpack_entry(source, row):
    entry = row["archive_entry"]
    header = source.fetch(entry["offset"], 30)
    signature, version, flags, compression, _, _, crc, compressed, size, name_len, extra_len = struct.unpack("<4s5H3I2H", header)
    if signature != b"PK\x03\x04" or flags & 1 or compression != entry["compression"]:
        raise RuntimeError("Invalid ZIP local header")
    if compression not in (0, 8) or name_len > 4096 or extra_len > 65535:
        raise RuntimeError("Unsupported ZIP entry")
    name = source.fetch(entry["offset"] + 30, name_len).decode("utf-8")
    if name != entry["name"]:
        raise RuntimeError("ZIP entry name mismatch")
    packed = source.fetch(entry["offset"] + 30 + name_len + extra_len, entry["compressed_size"])
    if compression == 8:
        decoder = zlib.decompressobj(-15)
        raw = decoder.decompress(packed, entry["size"] + 1)
        if len(raw) > entry["size"] or not decoder.eof or decoder.unused_data:
            raise RuntimeError("Invalid compressed entry length")
    else:
        raw = packed
    if (len(raw) != row["size_bytes"] or zlib.crc32(raw) != entry["crc32"]
            or hashlib.sha256(raw).hexdigest() != row["sha256"]):
        raise RuntimeError("Image checksum mismatch; no file saved")
    return raw


def download_images(*, directory=None, workers=4, ids=None):
    source_spec = manifest()
    rows = source_spec["images"]
    if ids:
        wanted = set(ids)
        rows = [r for r in rows if r["image_id"] in wanted]
        if {r["image_id"] for r in rows} != wanted:
            raise ValueError("Unknown image ID")
    if not 1 <= workers <= 8:
        raise ValueError("workers must be between 1 and 8")
    source = RangeSource(source_spec)

    def one(row):
        target = image_destination(row, directory)
        if valid_file(target, row):
            return "cached"
        raw = unpack_entry(source, row)
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, temp = tempfile.mkstemp(prefix=target.name + ".", suffix=".part", dir=target.parent)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(raw)
            os.replace(temp, target)
        finally:
            Path(temp).unlink(missing_ok=True)
        return "downloaded"

    counts = {"downloaded": 0, "cached": 0}
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(one, row) for row in rows]
        for i, future in enumerate(concurrent.futures.as_completed(futures), 1):
            counts[future.result()] += 1
            print(f"Images verified: {i}/{len(rows)}", flush=True)
    result = {"image_count": len(rows), **counts, "bytes_received": source.bytes_received,
              "archive_bytes": source_spec["archive_size"], "full_archive_downloaded": False,
              "all_sha256_verified": True, "paid_calls": 0}
    save(ROOT / "output/download_report.json", result)
    print(json.dumps(result))
    return result
