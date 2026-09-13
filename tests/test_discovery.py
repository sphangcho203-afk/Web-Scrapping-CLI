from internet_hands.discovery import (
    _robots_sitemaps,
    discover_from_html,
    discover_frontier_urls,
)


def test_discovers_machine_readable_links_and_json_ld():
    html = """
    <html><head>
      <link rel="alternate" type="application/rss+xml" href="/feed.xml">
      <link rel="alternate" type="application/feed+json" href="/feed.json">
      <link rel="alternate" type="application/json+oembed" href="/oembed?url=x">
      <link rel="manifest" href="/manifest.webmanifest">
      <link rel="alternate" href="/openapi.json">
      <script type="application/ld+json">{"@type":"WebSite","url":"https://example.com"}</script>
    </head><body>
      <a href="/docs/swagger.json">API docs</a>
    </body></html>
    """
    result = discover_from_html(html, "https://example.com/page")
    kinds = {item["kind"] for item in result["candidates"]}
    assert {"rss", "json_feed", "oembed", "web_manifest", "openapi_candidate"} <= kinds
    assert result["json_ld"] == [{"@type": "WebSite", "url": "https://example.com"}]


def test_robots_sitemaps_are_normalized_and_deduplicated():
    text = """
    User-agent: *
    Sitemap: /sitemap.xml
    Sitemap: https://example.com/sitemap.xml
    Sitemap: https://example.com/news.xml
    """
    assert _robots_sitemaps(text, "https://example.com") == [
        "https://example.com/sitemap.xml",
        "https://example.com/news.xml",
    ]


def test_frontier_extracts_sitemap_and_feed_urls():
    sitemap = """
    <?xml version="1.0"?>
    <urlset>
      <url><loc>https://example.com/a</loc></url>
      <url><loc>/b?x=1&amp;y=2</loc></url>
    </urlset>
    """
    assert discover_frontier_urls(
        sitemap,
        "https://example.com/sitemap.xml",
        content_type="application/xml",
    ) == [
        "https://example.com/a",
        "https://example.com/b?x=1&y=2",
    ]

    atom = """
    <feed xmlns="http://www.w3.org/2005/Atom">
      <entry><link href="https://example.com/post/1" /></entry>
    </feed>
    """
    assert discover_frontier_urls(
        atom,
        "https://example.com/feed.xml",
        content_type="application/atom+xml",
    ) == ["https://example.com/post/1"]


def test_frontier_extracts_json_feed_urls():
    payload = """
    {
      "version": "https://jsonfeed.org/version/1.1",
      "home_page_url": "https://example.com/",
      "items": [
        {"url": "https://example.com/post/1"},
        {"external_url": "https://external.example/article"}
      ]
    }
    """
    assert discover_frontier_urls(
        payload,
        "https://example.com/feed.json",
        content_type="application/feed+json",
    ) == [
        "https://example.com/",
        "https://example.com/post/1",
        "https://external.example/article",
    ]
