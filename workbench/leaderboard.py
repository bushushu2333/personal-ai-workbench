"""Read the public, server-rendered AIHOT model table without executing it.

The adapter deliberately fails closed when the table's meaning changes. Its
caller owns network access and cache retention; this module only accepts HTML.
"""

import json
import math
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit, urlunsplit


_BASE_URL = "https://aihot.news"
_PRICE_UNIT = "人民币 / 百万 Token"
_HEADERS = ("名次", "模型", "上线日期", "评测证据", "缓存价格", "输入价格", "输出价格", "AIHOT评分")
_HIDDEN = {"script", "style", "template", "noscript"}
_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
_UNKNOWN = {"", "—", "–", "-", "暂无", "未知", "待核验", "未核验", "未公开", "暂无价格", "N/A"}


@dataclass
class _Element:
    tag: str
    attrs: dict = field(default_factory=dict)
    children: list = field(default_factory=list)

    def text(self, include_hidden=False):
        if self.tag in _HIDDEN and not include_hidden:
            return ""
        return "".join(child if isinstance(child, str) else child.text(include_hidden) for child in self.children)

    def elements(self, tag, include_hidden=False):
        if self.tag in _HIDDEN and not include_hidden:
            return
        if self.tag == tag:
            yield self
        for child in self.children:
            if isinstance(child, _Element):
                yield from child.elements(tag, include_hidden)


class _Document(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = _Element("document")
        self.stack = [self.root]
        self.node_count = 0

    def handle_starttag(self, tag, attrs):
        self.node_count += 1
        if self.node_count > 20_000 or len(self.stack) > 128:
            raise ValueError("榜单 HTML 超出解析限制")
        node = _Element(tag, dict(attrs))
        self.stack[-1].children.append(node)
        if tag not in _VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in _VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                self.stack = self.stack[:index]
                break

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def _text(node):
    return " ".join(node.text().split())


def _detail_url(value, slug):
    try:
        parsed = urlsplit(urljoin(_BASE_URL, value))
    except (TypeError, ValueError) as exc:
        raise ValueError("榜单模型链接无效") from exc
    if (parsed.scheme != "https" or parsed.netloc != "aihot.news"
            or parsed.path != "/leaderboard/" + slug or len(parsed.query) > 200):
        raise ValueError("榜单模型链接不是 AIHOT 同域详情页")
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query, ""))


def _price(node):
    value = _text(node)
    if value in _UNKNOWN:
        return None
    if not re.fullmatch(r"[¥￥]\s*\d[\d,]*(?:\.\d+)?", value):
        raise ValueError("榜单价格格式发生变化")
    return value


def _release_date(node):
    times = list(node.elements("time"))
    value = times[0].attrs.get("datetime", "") if len(times) == 1 else _text(node)
    if value in _UNKNOWN:
        return None
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("榜单上线日期格式发生变化")
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("榜单上线日期无效") from exc
    return value


def _row(row):
    slug = row.attrs.get("data-slug", "")
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug):
        raise ValueError("榜单模型标识无效")
    cells = [node for node in row.children if isinstance(node, _Element) and node.tag == "td"]
    if len(cells) != 8:
        raise ValueError("榜单数据列数发生变化")
    rank_text = _text(cells[0])
    if not re.fullmatch(r"\d{1,3}", rank_text) or int(rank_text) < 1:
        raise ValueError("榜单名次无效")
    links = list(cells[1].elements("a"))
    vendors = list(cells[1].elements("small"))
    if not links or not vendors:
        raise ValueError("榜单缺少模型或厂商")
    name, vendor = _text(links[0]), _text(vendors[0])
    if not name or len(name) > 240 or not vendor or len(vendor) > 100 or "上线" in vendor:
        raise ValueError("榜单模型或厂商格式发生变化")
    score_nodes = list(cells[7].elements("strong"))
    score_text = _text(score_nodes[0]) if len(score_nodes) == 1 else ""
    if not re.fullmatch(r"-?\d+(?:\.\d+)?", score_text):
        raise ValueError("榜单评分不是有效数值")
    score = float(score_text)
    if not math.isfinite(score):
        raise ValueError("榜单评分不是有限数值")
    evidence = _text(cells[3])
    evaluations = re.search(r"(?<!\d)(\d{1,4})\s*项评测", evidence)
    coverage = re.search(r"覆盖\s*(\d{1,3})\s*%", evidence)
    if not evaluations or int(evaluations.group(1)) < 1 or not coverage or int(coverage.group(1)) > 100:
        raise ValueError("榜单评测证据格式发生变化")
    mobile_coverage = re.search(r"覆盖\s*(\d{1,3})\s*%", _text(cells[7]))
    if mobile_coverage and mobile_coverage.group(1) != coverage.group(1):
        raise ValueError("榜单重复覆盖率不一致")
    return {
        "rank": int(rank_text), "name": name, "vendor": vendor, "score": score,
        "coverage": int(coverage.group(1)), "evaluations_count": int(evaluations.group(1)),
        "input_price": _price(cells[5]), "output_price": _price(cells[6]), "cache_price": _price(cells[4]),
        "release_date": _release_date(cells[2]), "detail_url": _detail_url(links[0].attrs.get("href", ""), slug),
    }


def _metadata(root):
    pattern = re.compile(r"(\d+)\s*项评测\s*[·•|]\s*(\d+)\s*家机构\s*[·•|]\s*(\d{2}/\d{2}\s+\d{2}:\d{2})\s*更新")
    matches = [match for node in root.elements("p") for match in [pattern.fullmatch(_text(node))] if match]
    if len(matches) != 1:
        raise ValueError("榜单来源更新信息缺失或发生变化")
    evaluations, organizations, updated = matches[0].groups()
    try:
        # Validate the source's yearless display label without inventing a year.
        datetime.strptime("2000/" + updated, "%Y/%m/%d %H:%M")
    except ValueError as exc:
        raise ValueError("榜单来源更新时间无效") from exc
    if int(evaluations) < 1 or int(organizations) < 1:
        raise ValueError("榜单来源评测数量无效")
    return {"source_updated_label": updated, "evaluation_count": int(evaluations), "organization_count": int(organizations)}


def _validate_structured_data(root, items):
    lists = []
    for script in root.elements("script", include_hidden=True):
        if script.attrs.get("type", "").lower() != "application/ld+json":
            continue
        try:
            value = json.loads(script.text(include_hidden=True))
        except (ValueError, TypeError) as exc:
            raise ValueError("榜单结构化数据无效") from exc
        pending = [value]
        while pending:
            value = pending.pop()
            if isinstance(value, list):
                pending.extend(value)
            elif isinstance(value, dict):
                if value.get("@type") == "ItemList":
                    lists.append(value)
                if "@graph" in value:
                    pending.append(value["@graph"])
    if not lists:
        return
    if len(lists) != 1:
        raise ValueError("榜单结构化列表发生变化")
    listing = lists[0]
    declared = listing.get("numberOfItems")
    entries = listing.get("itemListElement")
    if (declared is not None and declared != len(items)) or not isinstance(entries, list) or len(entries) != len(items):
        raise ValueError("榜单行数与结构化数据不一致")
    for entry, item in zip(entries, items):
        if not isinstance(entry, dict) or entry.get("position") != item["rank"] or entry.get("name") != item["name"]:
            raise ValueError("榜单名次与结构化数据不一致")
        slug = urlsplit(item["detail_url"]).path.rsplit("/", 1)[-1]
        structured_url = _detail_url(entry.get("url", ""), slug)
        if urlsplit(structured_url).path != urlsplit(item["detail_url"]).path:
            raise ValueError("榜单链接与结构化数据不一致")


def parse_leaderboard(html: str) -> dict:
    """Return validated public AIHOT ranks and their display metadata.

    Unknown prices are ``None``; known prices retain the source's CNY display
    string. ``score`` is a capability score, while ``coverage`` is a percentage.
    No network access or script execution occurs. Invalid pages raise ValueError
    so callers can retain the last successful cache instead of publishing gaps.
    """
    if not isinstance(html, str) or not html.strip() or len(html) > 2_000_000:
        raise ValueError("榜单 HTML 为空或超出解析限制")
    document = _Document()
    document.feed(html)
    document.close()
    tables = [table for table in document.root.elements("table")
              if any("data-slug" in row.attrs for row in table.elements("tr"))]
    if len(tables) != 1:
        raise ValueError("未找到唯一的已排名模型表格")
    table = tables[0]
    headers = [_text(node) for node in table.elements("th")]
    normalized = [re.sub(r"\s+", "", value) for value in headers]
    if len(headers) != 8 or any(token not in value for token, value in zip(_HEADERS, normalized)):
        raise ValueError("榜单表头发生变化")
    if any("人民币" not in normalized[index] or "百万Token" not in normalized[index] for index in (4, 5, 6)):
        raise ValueError("榜单价格单位发生变化")
    items = [_row(row) for row in table.elements("tr") if "data-slug" in row.attrs]
    if not items or len(items) > 100 or [item["rank"] for item in items] != list(range(1, len(items) + 1)):
        raise ValueError("榜单排名重复、不连续或为空")
    if len({item["detail_url"].split("?", 1)[0] for item in items}) != len(items):
        raise ValueError("榜单模型重复")
    _validate_structured_data(document.root, items)
    return {"items": items, **_metadata(document.root), "price_unit": _PRICE_UNIT}
