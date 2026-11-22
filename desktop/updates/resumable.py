"""HTTP range-resumable download helper (urllib, no third-party deps)."""

from __future__ import annotations

from pathlib import Path

import urllib.request


class DownloadIncomplete(RuntimeError):
    pass


def http_download_resumable(url: str, target: Path, expected_size: int,
                            chunk_size: int = 1 << 20) -> Path:
    """Download url -> target(.part), resuming with HTTP Range when the
    partial file exists. Raises DownloadIncomplete on short files."""
    resumes = 0
    while True:
        offset = target.stat().st_size if target.exists() else 0
        if resumes > 50:
            raise DownloadIncomplete("too many interruptions")
        headers = {"Range": f"bytes={offset}-"} if offset else {}
        request = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(request, timeout=30) as response:
            if offset and response.status != 206:
                offset = 0  # server ignored range; restart
            mode = "ab" if offset else "wb"
            with open(target, mode) as fh:
                while True:
                    chunk = response.read(chunk_size)
                    if not chunk:
                        break
                    fh.write(chunk)
        size = target.stat().st_size
        if size >= expected_size:
            if size > expected_size:
                raise DownloadIncomplete(f"downloaded {size} > expected {expected_size}")
            return target
        resumes += 1
