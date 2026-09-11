#!/usr/bin/env python3
"""Find Cleveland Clinic page/image candidates for all uncached cards in parallel."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import time
from urllib.parse import quote_plus, urljoin, urlparse
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET


USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Safari/537.36"
DEFAULT_WORKERS = 8
DEFAULT_RESULTS = 5


def is_cleveland_url(value: str) -> bool:
    host = (urlparse(value).hostname or "").lower().rstrip(".")
    return host == "clevelandclinic.org" or host.endswith(".clevelandclinic.org")


def fetch(url: str, timeout: float) -> bytes:
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"})
    with urlopen(request, timeout=timeout) as response:
        return response.read()


def clean_text(value: str) -> str:
    return " ".join(re.sub(r"<[^>]+>", " ", value).split())


def search_pages(query: str, limit: int, timeout: float) -> list[dict[str, str]]:
    scoped = query if "site:" in query.casefold() else f"site:clevelandclinic.org {query}"
    url = "https://www.bing.com/search?format=rss&q=" + quote_plus(scoped)
    root = ET.fromstring(fetch(url, timeout))
    pages: list[dict[str, str]] = []
    for item in root.findall("./channel/item"):
        link = (item.findtext("link") or "").strip()
        if not is_cleveland_url(link):
            continue
        pages.append({
            "page_url": link,
            "title": clean_text(item.findtext("title") or ""),
            "snippet": clean_text(item.findtext("description") or ""),
        })
        if len(pages) >= limit:
            break
    return pages


class ImageParser(HTMLParser):
    def __init__(self, base_url: str):
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.images: list[dict[str, str]] = []
        self.title = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key.casefold(): value or "" for key, value in attrs}
        if tag.casefold() == "meta":
            key = (values.get("property") or values.get("name") or "").casefold()
            if key == "og:title" and values.get("content"):
                self.title = values["content"].strip()
            if key in {"og:image", "twitter:image"} and values.get("content"):
                self._add(values["content"], key)
        if tag.casefold() == "img":
            source = values.get("src") or values.get("data-src") or values.get("data-lazy-src")
            if source:
                self._add(source, values.get("alt", ""))

    def _add(self, source: str, label: str) -> None:
        url = urljoin(self.base_url, source.strip())
        if is_cleveland_url(url) and not url.lower().endswith(".svg"):
            self.images.append({"image_url": url, "alt": clean_text(label)})


def inspect_page(page: dict[str, str], timeout: float, image_limit: int) -> dict:
    parser = ImageParser(page["page_url"])
    parser.feed(fetch(page["page_url"], timeout).decode("utf-8", errors="replace"))
    seen: set[str] = set()
    images = []
    for image in parser.images:
        if image["image_url"] in seen:
            continue
        seen.add(image["image_url"])
        images.append(image)
        if len(images) >= image_limit:
            break
    return {**page, "page_title": parser.title or page["title"], "images": images}


def process_card(card: dict, limit: int, timeout: float, image_limit: int) -> dict:
    query = str(card.get("image_query") or card["word"]).strip()
    started = time.perf_counter()
    try:
        supplied_pages = card.get("candidate_pages") or []
        if supplied_pages:
            pages = [
                {"page_url": str(url), "title": "", "snippet": ""}
                for url in supplied_pages[:limit] if is_cleveland_url(str(url))
            ]
        else:
            pages = search_pages(query, limit, timeout)
    except Exception as error:
        return {
            "word": str(card["word"]), "image_query": query, "status": "search-failed",
            "error": f"{type(error).__name__}: {error}", "pages": [],
            "seconds": round(time.perf_counter() - started, 3),
        }
    inspected = []
    page_errors = []
    for page in pages:
        try:
            inspected.append(inspect_page(page, timeout, image_limit))
        except Exception as error:
            page_errors.append({"page_url": page["page_url"], "error": f"{type(error).__name__}: {error}"})
    status = "success" if inspected and not page_errors else "incomplete" if inspected or page_errors else "no-results"
    return {
        "word": str(card["word"]), "image_query": query,
        "status": status,
        "pages": inspected, "page_errors": page_errors,
        "seconds": round(time.perf_counter() - started, 3),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("spec", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    parser.add_argument("--results-per-term", type=int, default=DEFAULT_RESULTS)
    parser.add_argument("--images-per-page", type=int, default=8)
    parser.add_argument("--timeout", type=float, default=15.0)
    args = parser.parse_args()
    if not 1 <= args.workers <= 16:
        parser.error("--workers must be between 1 and 16")

    spec = json.loads(args.spec.expanduser().resolve().read_text(encoding="utf-8"))
    cards = [card for card in spec.get("cards", []) if isinstance(card, dict)]
    started = time.perf_counter()
    results: list[dict | None] = [None] * len(cards)
    with ThreadPoolExecutor(max_workers=min(args.workers, len(cards) or 1)) as pool:
        futures = {
            pool.submit(process_card, card, args.results_per_term, args.timeout, args.images_per_page): index
            for index, card in enumerate(cards)
        }
        for future in as_completed(futures):
            results[futures[future]] = future.result()

    final = [item for item in results if item is not None]
    payload = {
        "source_policy": "candidate pages and images are restricted to clevelandclinic.org",
        "automatic_no_image_decisions": False,
        "cards": len(final),
        "success": sum(item["status"] == "success" for item in final),
        "incomplete": sum(item["status"] != "success" for item in final),
        "total_seconds": round(time.perf_counter() - started, 3),
        "results": final,
    }
    args.output.expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
    args.output.expanduser().resolve().write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({key: payload[key] for key in ("cards", "success", "incomplete", "total_seconds")}, indent=2))


if __name__ == "__main__":
    main()
