"""Fetch user-selected artwork at a pinned commit; never execute upstream code.

Artwork is excluded from Git. Its rights are separate from the Octop source.
The initial lock is created explicitly; subsequent builds verify every hash.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMMIT = "a868a2619762c1b6a31646f0cb568aad3ebffbde"
SOURCE = f"https://raw.githubusercontent.com/AlleyBo55/doraemon/{COMMIT}/art/dora-sprites/"
ANIMATIONS = {
    "idle": ("emotion-calm", 4, 260),
    "working": ("action-coding_thinking", 3, 180),
    "listening": ("action-chat_question", 3, 180),
    "speaking": ("action-chat_answer", 3, 150),
    "success": ("emotion-joy", 4, 150),
    "error": ("emotion-concern", 4, 200),
    "dragging": ("action-take_copter", 3, 120),
    "sleep": ("action-nap", 3, 300),
    "walking": ("action-walk", 3, 150),
}
NOTICE = """Octop desktop companion - locally selected character preview

Character: Doraemon (user-selected).
Source repository: https://github.com/AlleyBo55/doraemon
Pinned source commit: a868a2619762c1b6a31646f0cb568aad3ebffbde
Upstream credits the Doraemon Shimeji FREE pack by Cachomon:
https://www.deviantart.com/cachomon/art/Doraemon-Shimeji-FREE-505596307
Doraemon character: Fujiko F. Fujio / Shogakukan and respective rights holders.

The upstream README describes MIT licensing for its software. That statement
does not provide an independent grant over the character or third-party art.
No MIT, CC BY, or public-domain license is assigned to the artwork here.
This local preview is not a published Octop release. Verify the artwork and
character distribution terms before bundling them in a public/company release.
Artwork is deliberately excluded from the public source tree. The application
supports replacing this local asset folder while keeping the same UI and APIs.
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write-lock", action="store_true")
    args = parser.parse_args()
    lock_path = ROOT / "asset-lock.json"
    if not args.write_lock and not lock_path.is_file():
        raise SystemExit("Missing asset lock. Review the selected source before --write-lock.")
    old = json.loads(lock_path.read_text()) if lock_path.is_file() else None
    target = ROOT / "assets/downloaded/doraemon"
    target.mkdir(parents=True, exist_ok=True)
    animations = {
        state: {
            "frames": [f"{prefix}-{index:02d}.png" for index in range(1, count + 1)],
            "frameDelay": delay,
        }
        for state, (prefix, count, delay) in ANIMATIONS.items()
    }
    names = sorted({name for animation in animations.values() for name in animation["frames"]})

    def fetch(name: str) -> tuple[str, str]:
        file = target / name
        expected = (old or {}).get("files", {}).get(name)
        if (
            file.is_file()
            and expected
            and hashlib.sha256(file.read_bytes()).hexdigest() == expected
        ):
            return name, expected
        for attempt in range(3):
            try:
                request = urllib.request.Request(
                    SOURCE + name, headers={"User-Agent": "OctopCompanion-asset-verification"}
                )
                with urllib.request.urlopen(request, timeout=35) as response:
                    content = response.read(2_000_001)
                if len(content) > 2_000_000 or not content.startswith(b"\x89PNG\r\n\x1a\n"):
                    raise ValueError(f"Invalid PNG: {name}")
                digest = hashlib.sha256(content).hexdigest()
                if expected and expected != digest:
                    raise ValueError(f"Artwork checksum changed: {name}")
                file.write_bytes(content)
                return name, digest
            except Exception:
                if attempt == 2:
                    raise
                time.sleep(1)
        raise AssertionError("unreachable")

    with ThreadPoolExecutor(max_workers=6) as pool:
        hashes = dict(pool.map(fetch, names))
    lock = {
        "repository": "https://github.com/AlleyBo55/doraemon",
        "source_commit": COMMIT,
        "artwork_license": "separate rights; local preview; distribution grant not verified",
        "files": hashes,
    }
    if args.write_lock:
        lock_path.write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")
    elif old != lock:
        raise SystemExit("Asset lock does not match the selected source.")
    (target / "pet.json").write_text(
        json.dumps({"name": "Doraemon preview", "animations": animations}, indent=2) + "\n"
    )
    (target / "ASSET-NOTICE.txt").write_text(NOTICE, encoding="utf-8")
    print(
        json.dumps(
            {"verified_png_frames": len(hashes), "states": len(animations), "source_commit": COMMIT}
        )
    )


if __name__ == "__main__":
    main()
