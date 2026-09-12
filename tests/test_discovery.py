from internet_hands.discovery import _robots_sitemaps, discover_from_html


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
