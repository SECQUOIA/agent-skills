#!/usr/bin/env python3
"""Read-only check of owned, static HTML fragment links; no network requests."""

import argparse
import json
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote, unquote, urljoin, urlsplit


class Page(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.anchors = set()
        self.links = []
        self.base = None
        self.feed(text)

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        if attrs.get("id"):
            self.anchors.add(attrs["id"])
        if tag == "a" and attrs.get("name"):
            self.anchors.add(attrs["name"])
        if tag == "a" and attrs.get("href"):
            self.links.append(attrs["href"])
        if tag == "base" and self.base is None and attrs.get("href"):
            self.base = attrs["href"]


def check(root, base_url):
    root = Path(root).resolve()
    if not root.is_dir():
        raise ValueError("rendered root must be an existing directory")
    base = urlsplit(base_url)
    if base.scheme not in ("http", "https") or not base.netloc or base.query or base.fragment:
        raise ValueError("base URL must be an HTTP(S) directory URL without query or fragment")
    base_url = base_url.rstrip("/") + "/"
    base = urlsplit(base_url)
    cache = {}

    def page(path):
        path = path.resolve()
        if not path.is_relative_to(root):
            raise ValueError("HTML input resolves outside the rendered root")
        if path not in cache:
            cache[path] = Page(path.read_text(encoding="utf-8"))
        return cache[path]

    sources = sorted(set(root.rglob("*.html")) | set(root.rglob("*.htm")))
    if not sources:
        raise ValueError("no rendered HTML pages found")
    broken = []
    checked = 0
    skipped = 0
    for source in sources:
        document = page(source)
        name = source.relative_to(root).as_posix()
        source_url = urljoin(base_url, quote(name, safe="/"))
        source_base = urljoin(source_url, document.base) if document.base else source_url
        for href in document.links:
            url = urlsplit(urljoin(source_base, href))
            fragment = unquote(url.fragment).split(":~:", 1)[0]
            if not fragment:
                continue  # Empty and native text-only fragments are not named anchors.
            if (url.scheme, url.netloc) != (base.scheme, base.netloc) or not url.path.startswith(base.path):
                skipped += 1
                continue
            target = root / unquote(url.path[len(base.path):])
            if url.path.endswith("/") or target.is_dir() or not target.suffix:
                target = target / "index.html"
            if target.suffix.lower() not in (".html", ".htm"):
                skipped += 1
                continue
            checked += 1
            if not target.resolve().is_relative_to(root):
                reason = "target resolves outside rendered root"
            elif not target.is_file():
                reason = "missing HTML page"
            elif fragment in page(target).anchors or fragment.lower() == "top":
                continue  # HTML's fallback top fragment needs no explicit ID.
            else:
                reason = "missing case-sensitive anchor"
            broken.append({"page": name, "href": href, "reason": reason})
    return {"passed": not broken, "html_pages": len(sources), "checked_fragments": checked,
            "skipped_external_or_non_html": skipped, "broken": broken}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path, help="rendered HTML directory")
    parser.add_argument("--base-url", required=True, help="public directory URL corresponding to root")
    args = parser.parse_args()
    try:
        report = check(args.root, args.base_url)
    except (OSError, ValueError) as error:
        print(json.dumps({"error": str(error)}))
        return 2
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
