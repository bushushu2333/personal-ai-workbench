import unittest

from workbench.trending import parse_trending


def row(repository="owner/project", total="1,234", daily="123", description="A useful project.", language="Python", href=None):
    language_html = '<span itemprop="programmingLanguage">' + language + '</span>' if language else ""
    return '''<article class="extra Box-row">
      <a href="/login?return_to=ignored">Star</a>
      <h2><a href="%s"><svg><path></path></svg><span>%s</span></a></h2>
      <p>%s</p><div>%s<a href="/%s/stargazers"><svg></svg>%s</a>
      <a href="/%s/forks">15</a><span><svg></svg>%s stars today</span></div>
    </article>''' % (href or "/" + repository, repository, description, language_html, repository, total, repository, daily)


class TrendingTests(unittest.TestCase):
    def test_extracts_plain_fields_and_ignores_script_style_and_other_links(self):
        source = "<script>untrusted outside script</script>" + row(description='Useful &amp; fast <b>tool</b>.<script>steal()</script><style>evil css</style><img src="x" onerror="bad()">')
        item = parse_trending(source)[0]
        self.assertEqual(item, {
            "repository": "owner/project", "title": "owner/project", "summary": "Useful & fast tool .",
            "url": "https://github.com/owner/project", "language": "Python", "total_stars": 1234,
            "stars_today": 123, "trending_rank": 1, "growth_window": "today",
        })
        self.assertNotIn("steal", repr(item))
        self.assertNotIn("onerror", repr(item))
        self.assertNotIn("evil", repr(item))

    def test_sorts_daily_growth_caps_ten_and_keeps_source_rank(self):
        source = "".join(row("owner/repo%d" % i, total="10000", daily=str(i)) for i in range(12))
        items = parse_trending(source)
        self.assertEqual(len(items), 10)
        self.assertEqual([item["stars_today"] for item in items], list(range(11, 1, -1)))
        self.assertEqual(items[0]["trending_rank"], 12)

    def test_case_insensitive_dedup_preserves_first_source_observation(self):
        items = parse_trending(row("Owner/Project", daily="100") + row("owner/project", daily="200") + row("owner/other", daily="100"))
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["repository"], "Owner/Project")
        self.assertEqual(items[0]["stars_today"], 100)
        self.assertEqual(items[1]["trending_rank"], 3)

    def test_exact_github_absolute_link_and_optional_language(self):
        item = parse_trending(row(href="https://github.com/owner/project", language=None))[0]
        self.assertEqual(item["url"], "https://github.com/owner/project")
        self.assertIsNone(item["language"])

    def test_rejects_non_repository_or_external_links(self):
        for href in ("https://evil.example/owner/project", "https://github.com.evil.test/owner/project", "//github.com/owner/project", "http://github.com/owner/project", "https://user@github.com/owner/project", "/owner/project/issues", "/owner/..", "/owner/project?x=1", "/owner/project#fragment", "/owner/%70roject", "/owner/project\\escape", "/owner/proj\nect", "owner/project"):
            with self.subTest(href=href), self.assertRaises(ValueError):
                parse_trending(row(href=href))

    def test_invalid_rows_do_not_hide_remaining_valid_rows(self):
        items = parse_trending(row(href="https://evil.example/owner/project") + row("valid/project", daily="321"))
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["repository"], "valid/project")
        self.assertEqual(items[0]["trending_rank"], 2)

    def test_rejects_invalid_or_unreasonable_star_counts(self):
        for total, daily in (("-1", "0"), ("1.2k", "1"), ("1,23", "1"), ("100", "-2"), ("100", "1,2"), ("100", "101"), ("1000000001", "1"), ("100", "2e1"), ("100", "")):
            with self.subTest(total=total, daily=daily), self.assertRaises(ValueError):
                parse_trending(row(total=total, daily=daily))

    def test_requires_exact_box_row_class_and_verifiable_rows(self):
        for html in ("", "<html>unavailable</html>", row().replace("extra Box-row", "Box-row-other"), "<article class='Box-row'><h2>No repository link</h2></article>"):
            with self.subTest(html=html[:70]), self.assertRaises(ValueError):
                parse_trending(html)

    def test_malformed_or_truncated_relevant_html_raises(self):
        for html in (row().replace("</article>", ""), row().replace("</h2>", ""), "<article class='Box-row'><article></article></article>"):
            with self.subTest(html=html[:70]), self.assertRaises(ValueError):
                parse_trending(html)


if __name__ == "__main__":
    unittest.main()
