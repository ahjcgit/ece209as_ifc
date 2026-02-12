from __future__ import annotations

import re
import urllib.request
from dataclasses import dataclass

from .labels import Label


@dataclass(frozen=True)
class ToolResult:
    text: str
    label: Label


def _strip_html(html: str) -> str:
    text = re.sub(r"<script.*?>.*?</script>", " ", html, flags=re.S | re.I)
    text = re.sub(r"<style.*?>.*?</style>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


class WebFetcher:
    def __init__(self, user_agent: str = "IFC-Agent/0.1") -> None:
        self._user_agent = user_agent

    def fetch(self, url: str, label: Label) -> ToolResult:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": self._user_agent},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            html = resp.read().decode("utf-8", errors="replace")
        return ToolResult(text=_strip_html(html), label=label)

