import json
import unittest

from workbench.leaderboard import parse_leaderboard


HEADERS = """<thead><tr><th>名次<button>名次</button></th><th>模型</th><th>上线日期▲</th>
<th>评测证据▲</th><th>缓存价格<small>人民币 / 百万 Token</small></th>
<th>输入价格<small>人民币 / 百万 Token</small></th><th>输出价格<small>人民币 / 百万 Token</small></th>
<th>AIHOT 评分<button>AIHOT 评分 i</button></th></tr></thead>"""


def row(rank=1, slug="alpha-model", name="Alpha &amp; Omega", score="73.9", coverage=96, price="¥1.34", release=None, href=None):
    release = '<time datetime="2026-09-22">2026-09-22</time>' if release is None else release
    href = href or "/leaderboard/" + slug + "?from=coding"
    return f"""<tr data-slug="{slug}"><td>{rank:02d}</td>
<td><a href="{href}"><strong>{name}</strong></a><small>Open &amp; Co</small>
<small>Open &amp; Co · 9月22日上线</small></td><td>{release}</td>
<td><span>33<!-- --> 项评测</span><span>覆盖 <!-- -->{coverage}<!-- -->%</span></td>
<td>{price}</td><td>¥26.82</td><td>¥134.09</td>
<td><strong>{score}</strong><small>覆盖 {coverage}%</small></td></tr>"""


def page(rows=None, structured=None):
    scripts = "" if structured is None else '<script type="application/ld+json">' + json.dumps(structured) + '</script>'
    return f"""<!doctype html><html><head>{scripts}</head><body>
<p>35<!-- --> 项评测<span>·</span>7<!-- --> 家机构<span>·</span>10/07 14:06<!-- --> 更新</p>
<section aria-labelledby="lb-board-title"><h2 id="lb-board-title">编程榜</h2>
<table>{HEADERS}<tbody>{row() if rows is None else rows}</tbody></table></section></body></html>"""


class LeaderboardTests(unittest.TestCase):
    def test_parses_real_display_values_and_distinguishes_score_from_coverage(self):
        result = parse_leaderboard(page())
        self.assertEqual(result["source_updated_label"], "10/07 14:06")
        self.assertEqual(result["evaluation_count"], 35)
        self.assertEqual(result["organization_count"], 7)
        self.assertEqual(result["price_unit"], "人民币 / 百万 Token")
        self.assertEqual(result["items"], [{
            "rank": 1, "name": "Alpha & Omega", "vendor": "Open & Co", "score": 73.9,
            "coverage": 96, "evaluations_count": 33, "cache_price": "¥1.34",
            "input_price": "¥26.82", "output_price": "¥134.09", "release_date": "2026-09-22",
            "detail_url": "https://aihot.news/leaderboard/alpha-model?from=coding",
        }])
        self.assertIsInstance(result["items"][0]["score"], float)

    def test_unknown_prices_are_null_and_zero_price_is_preserved(self):
        for unknown in ("待核验", "—", "未公开"):
            with self.subTest(unknown=unknown):
                item = parse_leaderboard(page(row(price=unknown, release="—")))["items"][0]
                self.assertIsNone(item["cache_price"])
                self.assertIsNone(item["release_date"])
                self.assertEqual(item["input_price"], "¥26.82")
        self.assertEqual(parse_leaderboard(page(row(price="¥0")))["items"][0]["cache_price"], "¥0")

    def test_unranked_rows_and_hidden_markup_are_excluded_without_executing_scripts(self):
        html = page(row() + '<tr><td>暂不排名</td><td>Pending</td></tr>')
        hidden = '<script>throw new Error("do not execute"); document.write("<table><tr data-slug=evil></tr></table>")</script>'
        hidden += '<style>.fake { content: "999 项评测 · 9 家机构 · 10/07 14:06 更新" }</style>'
        hidden += '<template><table><tr data-slug="hidden-model"><td>99</td></tr></table></template>'
        html = html.replace("</body>", '<section><h2>暂不排名</h2><a href="/leaderboard/pending">Pending 99.9</a></section>' + hidden + "</body>")
        self.assertEqual([item["name"] for item in parse_leaderboard(html)["items"]], ["Alpha & Omega"])

    def test_same_origin_details_only_and_escaped_text_remains_plain_text(self):
        item = parse_leaderboard(page(row(name="Alpha &lt;beta&gt; &quot;One&quot;")))["items"][0]
        self.assertEqual(item["name"], 'Alpha <beta> "One"')
        for href in ("https://evil.example/leaderboard/alpha-model", "//evil.example/leaderboard/alpha-model",
                     "javascript:alert(1)", "https://aihot.news.evil.example/leaderboard/alpha-model",
                     "https://aihot.news/leaderboard/another-model", "https://user@aihot.news/leaderboard/alpha-model"):
            with self.subTest(href=href), self.assertRaises(ValueError):
                parse_leaderboard(page(row(href=href)))

    def test_changed_columns_units_and_invalid_numbers_raise_instead_of_returning_partial_table(self):
        changes = [
            page().replace("评测证据", "Unknown evidence"),
            page().replace("人民币", "美元"),
            page(row(score="NaN")), page(row(score="73.9%")), page(row(coverage=101)),
            page(row(price="$1.34")), page(row(release='<time datetime="2026-02-30">invalid</time>')),
            page().replace('<td>¥134.09</td>', ""),
            page().replace("35<!-- --> 项评测", "35 个资料"),
            page().replace("10/07 14:06", "13/07 25:06"),
        ]
        for html in changes:
            with self.subTest(html=html[:80]), self.assertRaises(ValueError):
                parse_leaderboard(html)

    def test_rank_integrity_rejects_duplicate_or_missing_rank_and_model(self):
        bad_rows = [row() + row(slug="beta-model"), row(rank=2),
                    row() + row(rank=3, slug="beta-model"), row() + row(rank=2)]
        for rows in bad_rows:
            with self.subTest(rows=rows[:80]), self.assertRaises(ValueError):
                parse_leaderboard(page(rows))

    def test_jsonld_checks_rank_name_and_count_without_needing_query_on_canonical_url(self):
        data = {"@type": "ItemList", "numberOfItems": 1, "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Alpha & Omega", "url": "https://aihot.news/leaderboard/alpha-model"}]}
        self.assertEqual(len(parse_leaderboard(page(structured=[data]))["items"]), 1)
        for field, value in (("position", 2), ("name", "Different"), ("url", "https://evil.example/leaderboard/alpha-model")):
            changed = json.loads(json.dumps(data))
            changed["itemListElement"][0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                parse_leaderboard(page(structured=changed))
        data["numberOfItems"] = 2
        with self.assertRaises(ValueError):
            parse_leaderboard(page(structured=data))

    def test_empty_error_pages_and_oversized_html_fail(self):
        for html in ("", "<html>Service unavailable</html>", page(""), "x" * 2_000_001, None):
            with self.subTest(value=str(html)[:80]), self.assertRaises(ValueError):
                parse_leaderboard(html)


if __name__ == "__main__":
    unittest.main()
