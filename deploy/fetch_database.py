"""Download the TravelIntel warehouse database from GitHub LFS on first start.

The database (~1.9 GB) is too large to bake into a container image, so the
server downloads it once into a persistent volume. Later starts find the file
and skip the download. Configure with environment variables:

    TRAVELINTEL_DB_PATH   where the database lives (default: /data/travelintel_warehouse.db)
    TRAVELINTEL_DB_URL    direct download URL (default: the Hugging Face dataset copy)
    TRAVELINTEL_DB_REPO   GitHub repo holding the LFS object, used when TRAVELINTEL_DB_URL is empty
    TRAVELINTEL_DB_OID    sha256 of the LFS object
    TRAVELINTEL_DB_SIZE   size in bytes of the LFS object
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import urllib.request
from pathlib import Path

DB_PATH = Path(os.environ.get("TRAVELINTEL_DB_PATH", "/data/travelintel_warehouse.db"))
REPO = os.environ.get("TRAVELINTEL_DB_REPO", "RamyaSS-gif/TravelIntel")
OID = os.environ.get(
    "TRAVELINTEL_DB_OID",
    "df5939e1466b74647cc1c7173bb95c93ec70d516a3d2b055e7338d67dc16b0e9",
)
SIZE = int(os.environ.get("TRAVELINTEL_DB_SIZE", "1945145344"))
# Direct download URL (e.g. a Hugging Face dataset file). When unset, the
# file is fetched from the GitHub repo's LFS storage instead.
DIRECT_URL = os.environ.get(
    "TRAVELINTEL_DB_URL",
    "https://huggingface.co/datasets/ramya2261324/travelintel-warehouse/resolve/main/travelintel_warehouse.db",
)
CHUNK = 8 * 1024 * 1024


def _download_url() -> str:
    if DIRECT_URL:
        return DIRECT_URL
    body = json.dumps(
        {
            "operation": "download",
            "transfers": ["basic"],
            "objects": [{"oid": OID, "size": SIZE}],
        }
    ).encode()
    request = urllib.request.Request(
        f"https://github.com/{REPO}.git/info/lfs/objects/batch",
        data=body,
        headers={
            "Accept": "application/vnd.git-lfs+json",
            "Content-Type": "application/vnd.git-lfs+json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        payload = json.load(response)
    obj = payload["objects"][0]
    if "error" in obj:
        raise RuntimeError(f"GitHub LFS refused the download: {obj['error']}")
    return obj["actions"]["download"]["href"]


def main() -> int:
    if DB_PATH.is_file() and DB_PATH.stat().st_size >= SIZE * 0.9:
        print(f"[fetch-db] Database present at {DB_PATH}; skipping download.")
        return 0

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    partial = DB_PATH.with_suffix(DB_PATH.suffix + ".part")
    print(f"[fetch-db] Downloading {SIZE / 1e9:.2f} GB database from {REPO} ...")
    digest = hashlib.sha256()
    written = 0
    with urllib.request.urlopen(_download_url(), timeout=120) as response, partial.open("wb") as out:
        while chunk := response.read(CHUNK):
            out.write(chunk)
            digest.update(chunk)
            written += len(chunk)
            if written % (256 * 1024 * 1024) < CHUNK:
                print(f"[fetch-db]   {written / 1e6:,.0f} MB / {SIZE / 1e6:,.0f} MB", flush=True)

    if written != SIZE or digest.hexdigest() != OID:
        partial.unlink(missing_ok=True)
        print("[fetch-db] Download incomplete or checksum mismatch.", file=sys.stderr)
        return 1

    partial.replace(DB_PATH)
    print(f"[fetch-db] Database ready at {DB_PATH}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
