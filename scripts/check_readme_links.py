#!/usr/bin/env python3
"""Check every external link in README.md.

The profile README leans on a lot of third-party services (shields.io,
streak-stats, raw.githubusercontent ...). Those rot quietly: a renamed
branch or a retired badge host turns into a 404 and nobody notices until
it is visible on the profile page.

This script extracts all http(s) URLs, probes them concurrently and exits
non-zero if any link is dead. Stdlib only, so CI needs no extra deps.

Usage:
    python3 scripts/check_readme_links.py [path-to-markdown ...]
"""

from __future__ import annotations

import re
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote

URL_RE = re.compile(r"https?://[^\s)<>\"'\]]+")
TRAILING = ".,;:"
TIMEOUT = 20
USER_AGENT = "Mozilla/5.0 (compatible; readme-link-check)"
OK_CODES = range(200, 400)


def extract_urls(text: str) -> list[str]:
    """Return unique, de-duplicated URLs, stripped of trailing punctuation."""
    seen: dict[str, None] = {}
    for raw in URL_RE.findall(text):
        url = raw.rstrip(TRAILING)
        seen.setdefault(url, None)
    return list(seen)


def probe(url: str) -> tuple[int | str, str]:
    """Return (status, url). Status is an int HTTP code or an error string."""
    # Badge URLs carry emoji, which urllib refuses to encode on its own.
    target = quote(url, safe=":/?#[]@!$&'()*+,;=%~")
    for method in ("HEAD", "GET"):
        req = urllib.request.Request(target, method=method)
        req.add_header("User-Agent", USER_AGENT)
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                return resp.status, url
        except urllib.error.HTTPError as exc:
            if method == "HEAD" and exc.code in (400, 403, 405, 501):
                continue  # server dislikes HEAD; retry with GET
            return exc.code, url
        except Exception as exc:  # noqa: BLE001 - report, never crash
            if method == "HEAD":
                continue
            return type(exc).__name__, url
    return "unreachable", url


def main(argv: list[str]) -> int:
    paths = argv[1:] or ["README.md"]
    urls: list[str] = []
    for path in paths:
        try:
            with open(path, encoding="utf-8") as handle:
                text = handle.read()
        except OSError as exc:
            print(f"error: cannot read {path}: {exc}", file=sys.stderr)
            return 2
        found = extract_urls(text)
        print(f"{path}: {len(found)} unique links")
        urls.extend(found)

    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(probe, urls))

    dead = [(status, url) for status, url in results if not (
        isinstance(status, int) and status in OK_CODES
    )]

    for status, url in sorted(dead, key=lambda item: str(item[1])):
        print(f"DEAD [{status}] {url}")

    total, bad = len(results), len(dead)
    print(f"\nchecked {total} links, {total - bad} ok, {bad} dead")
    if bad:
        print("::error::README contains dead links (see above)" if _in_ci() else "")
        return 1
    return 0


def _in_ci() -> bool:
    import os

    return os.environ.get("GITHUB_ACTIONS") == "true"


if __name__ == "__main__":
    sys.exit(main(sys.argv))
