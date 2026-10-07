"""Extract bounded, plain-text records from GitHub's public daily Trending page."""

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import urlsplit


_VOID_TAGS = frozenset(("area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"))
_REPOSITORY = re.compile(r"/([A-Za-z0-9][A-Za-z0-9-]{0,38})/([A-Za-z0-9_.-]{1,100})/?\Z")
_COUNT = re.compile(r"(?:0|[1-9][0-9]*|[1-9][0-9]{0,2}(?:,[0-9]{3})+)\Z")
_MAX_STARS = 1_000_000_000


@dataclass
class _Node:
    tag: str
    attrs: dict = field(default_factory=dict)
    children: list = field(default_factory=list)

    def text(self):
        return " ".join(child.text() if isinstance(child, _Node) else child for child in self.children)

    def descendants(self, tag):
        for child in self.children:
            if isinstance(child, _Node):
                if child.tag == tag:
                    yield child
                yield from child.descendants(tag)


def _plain(value, limit):
    # HTMLParser decodes entities; remove any encoded markup too. Consumers
    # receive source text, never HTML, CSS, script, SVG or event attributes.
    value = re.sub(r"<[^>]*>", "", value)
    value = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", value)
    return re.sub(r"\s+", " ", value).strip()[:limit]


def _github_path(href):
    if not isinstance(href, str) or len(href) > 300 or re.search(r"[\s\x00-\x1f\x7f]", href):
        return None
    try:
        parts = urlsplit(href)
    except ValueError:
        return None
    if parts.query or parts.fragment:
        return None
    if parts.scheme or parts.netloc:
        if parts.scheme != "https" or parts.netloc.casefold() != "github.com":
            return None
    elif not href.startswith("/") or href.startswith("//"):
        return None
    if "%" in parts.path or "\\" in parts.path:
        return None
    return parts.path


def _count(value):
    if not _COUNT.fullmatch(value) or len(value) > 20:
        return None
    result = int(value.replace(",", ""))
    return result if 0 <= result <= _MAX_STARS else None


class _TrendingParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows = []
        self.stack = []
        self.ignored_tag = None
        self.node_count = 0

    def handle_starttag(self, tag, attrs):
        if self.ignored_tag:
            return
        if tag in ("script", "style"):
            self.ignored_tag = tag
            return
        attributes = dict(attrs)
        if not self.stack:
            if tag != "article" or "Box-row" not in (attributes.get("class") or "").split():
                return
            if len(self.rows) >= 100:
                raise ValueError("GitHub 日榜项目数量异常")
            self.stack = [_Node(tag, attributes)]
            return
        if tag == "article":
            raise ValueError("GitHub 日榜项目结构异常")
        self.node_count += 1
        if self.node_count > 20_000 or len(self.stack) >= 100:
            raise ValueError("GitHub 日榜页面结构过大")
        node = _Node(tag, attributes)
        self.stack[-1].children.append(node)
        if tag not in _VOID_TAGS:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in _VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if self.ignored_tag:
            if tag == self.ignored_tag:
                self.ignored_tag = None
            return
        if not self.stack or tag in _VOID_TAGS:
            return
        if self.stack[-1].tag != tag:
            raise ValueError("GitHub 日榜页面标签不完整")
        node = self.stack.pop()
        if tag == "article":
            self.rows.append(node)

    def handle_data(self, data):
        if self.stack and not self.ignored_tag:
            self.stack[-1].children.append(data)


def _record(row, rank):
    headings = list(row.descendants("h2"))
    if len(headings) != 1:
        return None
    links = list(headings[0].descendants("a"))
    if len(links) != 1:
        return None
    path = _github_path(links[0].attrs.get("href"))
    matched = _REPOSITORY.fullmatch(path or "")
    if not matched or matched[2] in (".", ".."):
        return None
    repository = "/".join(matched.groups())
    star_links = [link for link in row.descendants("a")
                  if (_github_path(link.attrs.get("href")) or "").casefold() == "/" + repository.casefold() + "/stargazers"]
    if len(star_links) != 1:
        return None
    total_stars = _count(_plain(star_links[0].text(), 100))
    daily_values = []
    for span in row.descendants("span"):
        daily = re.fullmatch(r"([0-9][0-9,]*)\s+stars?\s+today", _plain(span.text(), 100))
        if daily:
            daily_values.append(_count(daily[1]))
    if total_stars is None or len(daily_values) != 1 or daily_values[0] is None:
        return None
    stars_today = daily_values[0]
    if stars_today > total_stars:
        return None
    paragraphs = list(row.descendants("p"))
    languages = [span for span in row.descendants("span") if span.attrs.get("itemprop") == "programmingLanguage"]
    return {
        "repository": repository,
        "title": repository,
        "summary": _plain(paragraphs[0].text(), 1600) if paragraphs else "",
        "url": "https://github.com/" + repository,
        "language": (_plain(languages[0].text(), 80) or None) if languages else None,
        "total_stars": total_stars,
        "stars_today": stars_today,
        "trending_rank": rank,
        "growth_window": "today",
    }


def parse_trending(html: str) -> list[dict]:
    """Return up to ten daily leaders by published ``stars today`` count.

    GitHub's source rank is retained separately. Its calendar-day metric is
    not an exact rolling 24-hour delta. A broken or empty page raises so that
    callers can retain their previous successful snapshot.
    """
    if not isinstance(html, str) or not html.strip() or len(html) > 4 * 1024 * 1024:
        raise ValueError("GitHub 日榜页面为空或过大")
    parser = _TrendingParser()
    try:
        parser.feed(html)
        parser.close()
    except (RecursionError, AssertionError) as exc:
        raise ValueError("GitHub 日榜页面结构异常") from exc
    if parser.stack:
        raise ValueError("GitHub 日榜页面不完整")
    records = {}
    for rank, row in enumerate(parser.rows, start=1):
        item = _record(row, rank)
        if item:
            records.setdefault(item["repository"].casefold(), item)
    if not records:
        raise ValueError("GitHub 日榜未返回可核验的项目")
    return sorted(records.values(), key=lambda item: (-item["stars_today"], item["trending_rank"]))[:10]
