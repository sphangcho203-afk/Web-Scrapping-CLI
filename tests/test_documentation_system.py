from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"


def _docs() -> dict[str, list[str]]:
    import json

    raw = (WEB / "docs-content.js").read_text(encoding="utf-8").strip()
    prefix = "window.OPENCRAWL_DOCS = "
    assert raw.startswith(prefix)
    assert raw.endswith(";")
    return json.loads(raw[len(prefix) : -1])


def test_detailed_docs_are_composed_before_app_in_single_runtime() -> None:
    index = (WEB / "index.html").read_text(encoding="utf-8")
    site = (ROOT / "src/internet_hands/site.py").read_text(encoding="utf-8")

    assert index.count('<script src="/assets/') == 1
    assert '/assets/app.js' in index
    assert 'docs = WEB_ROOT / "docs-content.js"' in site
    assert "sources = [legal, docs, runtime, usage, monitors, datasets]" in site
    assert '"docs-content.js": "application/javascript"' not in site
    assert 'window.OPENCRAWL_DOCS || {' in (WEB / "app.js").read_text(encoding="utf-8")


def test_docs_cover_the_product_as_a_system_not_stub_pages() -> None:
    docs = _docs()
    required = {
        "introduction",
        "architecture",
        "quickstart",
        "account",
        "two-factor",
        "keys",
        "mcp",
        "oauth",
        "clients",
        "sync",
        "capabilities",
        "tool-mesh",
        "providers",
        "monitoring",
        "usage",
        "billing",
        "security",
        "errors",
        "troubleshooting",
    }
    assert required <= docs.keys()

    for slug in required:
        title, group, body = docs[slug]
        assert title.strip()
        assert group.strip()
        assert len(body) >= 800, slug
        assert body.count("<h2 id=") >= 2, slug

    corpus = "\n".join(page[2] for page in docs.values())
    assert "Internet Hands" not in corpus
    assert "{{ORIGIN}}/mcp" in corpus
    assert "mesh_route" in corpus
    assert "mesh_capability_resolve" in corpus
    assert "mesh_execute" in corpus
    assert "two_factor_unavailable" in corpus
    assert "Supabase Auth" in corpus
    assert "Neon" in corpus
    assert "Resend" in corpus


def test_client_guides_use_documented_host_specific_setup() -> None:
    clients = _docs()["clients"][2]

    assert "codex mcp add opencrawl --url {{ORIGIN}}/mcp" in clients
    assert "codex mcp list" in clients
    assert "claude mcp add --transport http opencrawl {{ORIGIN}}/mcp" in clients
    assert ".vscode/mcp.json" in clients
    assert '"type": "http"' in clients
    assert '"Authorization": "Bearer ${input:opencrawl-key}"' in clients
    assert ".cursor/mcp.json" in clients

    authoritative_links = [
        "https://help.openai.com/en/articles/12584461-developer-mode-and-mcp-apps-in-chatgpt",
        "https://developers.openai.com/learn/docs-mcp",
        "https://docs.anthropic.com/en/docs/claude-code/mcp",
        "https://code.visualstudio.com/docs/agent-customization/mcp-servers",
        "https://code.visualstudio.com/docs/agents/reference/mcp-configuration",
        "https://docs.cursor.com/context/model-context-protocol",
    ]
    for href in authoritative_links:
        assert href in clients


def test_connection_ui_routes_short_explanations_into_full_docs() -> None:
    app = (WEB / "app.js").read_text(encoding="utf-8")

    assert 'href="/docs/clients"' in app
    assert 'href="/docs/sync#remote-mcp"' in app
    assert 'href="/docs/tool-mesh"' in app
    assert 'href="/docs/oauth"' in app
    assert 'href="/docs/keys"' in app
    assert 'href="/docs/two-factor"' in app

    assert "Client → OpenCrawl" in app
    assert "OpenCrawl → provider / remote MCP" in app
    assert "codex mcp add opencrawl --url " in app
    assert "claude mcp add --transport http opencrawl " in app

    # The docs runtime builds a real page index from the page title, group and rendered text.
    assert "data-doc-search" in app
    assert "Search documentation" in app
    assert "location.hash" in app
