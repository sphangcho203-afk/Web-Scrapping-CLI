from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
CSS = (ROOT / "web" / "cognitive-foundation.css").read_text(encoding="utf-8")


def _run_brand_contract(tmp_path: Path, contract: str) -> None:
    """Exercise the shipped helpers without booting the browser router."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    runtime = tmp_path / "connected-app-brands.cjs"
    runtime.write_text(
        """
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(process.argv[2], 'utf8');
const end = source.indexOf('function toast(');
assert.ok(end > 0, 'Could not locate the browser helper boundary');
const context = vm.createContext({
  assert,
  URL,
  location: {origin: 'https://opencrawl.top'},
  document: {getElementById: () => null},
});
vm.runInContext(source.slice(0, end), context, {timeout: 1000});
vm.runInContext(
"""
        + json.dumps(contract)
        + ", context, {timeout: 1000});\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [node, str(runtime), str(ROOT / "web" / "app.js")],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_capability_workbench_has_global_page_headline_helper() -> None:
    assert "const pageHeadline =" in APP
    start = APP.index("async function dashCapabilities()")
    end = APP.index("/* === Extended authenticated surfaces", start)
    capability_source = APP[start:end]
    assert "pageHeadline('WEB CAPABILITIES'" in capability_source
    assert "headline('WEB CAPABILITIES'" not in capability_source


def test_connected_apps_use_provider_logos_end_to_end() -> None:
    assert "const providerBrands =" in APP
    assert "const providerDisplayName =" in APP
    assert "const safeProviderLogo =" in APP
    assert "const connectedAppMark =" in APP
    assert "data-provider-logo" in APP
    assert "connectedAppMark(appItem)" in APP
    assert "connectedAppMark(configured)" in APP
    assert "connectedAppMark(meta)" in APP
    assert "esc(providerDisplayName(appItem))" in APP
    assert "esc(providerDisplayName(item))" in APP
    assert ".connected-app-mark img" in CSS
    assert ".connected-app-logo-fallback" in CSS
    assert re.search(
        r"(?:^|})[^{}]*\[hidden\][^{}]*\{[^{}]*display\s*:\s*none\s*!important",
        CSS,
        re.IGNORECASE,
    ), "Logo fallbacks must respect hidden despite their display rules"


def test_connected_app_catalog_is_not_letter_avatar_only() -> None:
    old_catalog_avatar = (
        '<span class="connected-app-mark">'
        "+esc((item.name||toolkit||'?').slice(0,1).toUpperCase())+"
    )
    assert old_catalog_avatar not in APP
    assert "connected-catalog-intro" in APP
    assert "connected-catalog-state" in APP
    assert "connected-app-initials" not in APP
    assert "toolkitInitials" not in APP


def test_client_setup_uses_canonical_mcp_endpoint_and_brand_marks() -> None:
    assert "const endpoint='https://opencrawl.top/mcp';" in APP
    assert "platformMark('openai','OpenAI')" in APP
    assert "platformMark('anthropic','Anthropic')" in APP
    assert "platformMark('mcp','MCP')" in APP
    assert "platformBrandMark('vscode'" in APP
    assert "platformBrandMark('cursor'" in APP
    assert ".agent-tab-mark" in CSS


def test_screenshot_providers_render_bundled_logos_even_when_remote_logo_is_broken(
    tmp_path: Path,
) -> None:
    _run_brand_contract(
        tmp_path,
        r"""
const screenshotProviders = {
  gmail: 'Gmail', composio: 'Composio', github: 'GitHub',
  googlecalendar: 'Google Calendar', notion: 'Notion', googlesheets: 'Google Sheets',
  slack: 'Slack', supabase: 'Supabase', outlook: 'Outlook',
  perplexityai: 'Perplexity AI', discordbot: 'Discord', youtube: 'YouTube',
};
for (const [toolkit, name] of Object.entries(screenshotProviders)) {
  const brand = providerBrand(toolkit);
  assert.ok(brand, `Missing bundled logo for ${toolkit}`);
  assert.equal(providerDisplayName({toolkit, name: `auth_config_${toolkit}_1790558363098`}), name);
  const mark = connectedAppMark({
    toolkit, name: `auth_config_${toolkit}_1790558363098`,
    logo: 'https://broken.example/404.svg', svg: '<script>untrusted()</script>',
  });
  assert.match(mark, /<svg\b/, `No inline brand logo for ${toolkit}`);
  assert.match(mark, /<(?:path|polygon|circle|rect)\b/, `Empty logo for ${toolkit}`);
  assert.doesNotMatch(mark, /<img\b|connected-app-initials|auth_config_|untrusted/);
}
""",
    )


def test_provider_aliases_and_friendly_names(tmp_path: Path) -> None:
    _run_brand_contract(
        tmp_path,
        r"""
for (const [alias, canonical] of [
  ['Git Hub', 'github'], ['GITHUB', 'github'], ['Discord-Bot', 'discord'],
  ['Google Calendar', 'googlecalendar'], ['GOOGLE_sheets', 'googlesheets'],
  ['Microsoft Outlook', 'outlook'], ['Perplexity', 'perplexityai'],
  ['Visual Studio Code', 'vscode'],
]) {
  assert.equal(providerBrand(alias), providerBrands[canonical], `Alias ${alias} did not resolve`);
}
assert.ok(!providerBrand('unknown_service'));
assert.ok(!providerBrand('constructor'), 'Inherited Object properties are not brands');
assert.equal(providerDisplayName({toolkit: 'github', name: 'auth_config_github_123'}), 'GitHub');
assert.equal(providerDisplayName({toolkit: 'discordbot', name: 'Unhelpful config title'}), 'Discord');
assert.equal(providerDisplayName({toolkit: 'custom_service', name: 'My Custom App'}), 'My Custom App');
assert.equal(providerDisplayName({toolkit: 'custom_service', name: 'auth_config_custom_service_123'}), 'Custom Service');
const generic = connectedAppMark({toolkit: 'custom_service', name: 'My Custom App'});
assert.match(generic, /<svg\b/);
assert.doesNotMatch(generic, /<img\b|connected-app-initials/);
""",
    )


def test_provider_logo_urls_require_absolute_https_without_credentials(tmp_path: Path) -> None:
    _run_brand_contract(
        tmp_path,
        r"""
for (const value of [
  undefined, null, '', '/logo.svg', '//cdn.example/logo.svg',
  'http://cdn.example/logo.svg', 'javascript:alert(1)',
  'data:image/svg+xml,<svg onload="alert(1)"></svg>',
  'https://user:password@cdn.example/logo.svg', 'https://user@cdn.example/logo.svg',
  'https://:password@cdn.example/logo.svg', 'not a url',
]) {
  assert.equal(safeProviderLogo(value), '', `Unsafe logo accepted: ${value}`);
  const fallback = connectedAppMark({toolkit: 'unknown_service', logo: value});
  assert.match(fallback, /<svg\b/);
  assert.doesNotMatch(fallback, /<img\b|connected-app-initials/);
}
assert.equal(safeProviderLogo('https://cdn.example/logo.svg'), 'https://cdn.example/logo.svg');
const mark = connectedAppMark({
  toolkit: 'unknown_service', name: '<script>alert(1)</script>',
  logo: 'https://cdn.example/logo.svg?label=" onerror="alert(1)',
});
assert.match(mark, /<img\b[^>]*data-provider-logo/);
assert.match(mark, /connected-app-logo-fallback[^>]*hidden/);
assert.match(mark, /<svg\b/);
assert.doesNotMatch(mark, /<script>|\sonerror=|connected-app-initials/);
""",
    )


def test_remote_logo_failure_switches_to_generic_icon_without_double_binding(
    tmp_path: Path,
) -> None:
    _run_brand_contract(
        tmp_path,
        r"""
const makeImage = (complete, naturalWidth) => ({
  dataset: {}, hidden: false, complete, naturalWidth,
  nextElementSibling: {hidden: true}, listeners: [],
  addEventListener(type, handler, options) {this.listeners.push({type, handler, options});},
});
const loading = makeImage(false, 0);
const cachedFailure = makeImage(true, 0);
const successful = makeImage(true, 32);
const detachedFallback = makeImage(false, 0);
detachedFallback.nextElementSibling = null;
const images = [loading, cachedFailure, successful, detachedFallback];
const root = {querySelectorAll(selector) {
  assert.equal(selector, '[data-provider-logo]');
  return images;
}};
bindProviderLogoFallbacks(root);
assert.equal(loading.hidden, false, 'An in-flight logo must remain visible');
assert.equal(loading.nextElementSibling.hidden, true);
assert.equal(cachedFailure.hidden, true, 'An already-failed cached logo must be hidden');
assert.equal(cachedFailure.nextElementSibling.hidden, false);
assert.equal(successful.hidden, false);
assert.equal(successful.nextElementSibling.hidden, true);
bindProviderLogoFallbacks(root);
for (const img of images) {
  assert.equal(img.listeners.length, 1, 'Rebinding must not add duplicate handlers');
  assert.equal(img.listeners[0].type, 'error');
  assert.equal(img.listeners[0].options.once, true);
}
loading.listeners[0].handler();
assert.equal(loading.hidden, true);
assert.equal(loading.nextElementSibling.hidden, false);
assert.doesNotThrow(() => detachedFallback.listeners[0].handler());
bindProviderLogoFallbacks({querySelectorAll: () => []});
""",
    )


def test_client_editor_marks_are_distinct_brands(tmp_path: Path) -> None:
    _run_brand_contract(
        tmp_path,
        r"""
const vscode = platformBrandMark('vscode');
const cursor = platformBrandMark('cursor');
assert.match(vscode, /<svg\b/);
assert.match(cursor, /<svg\b/);
assert.notEqual(vscode, cursor);
assert.notEqual(vscode, platformMark('api'));
assert.notEqual(cursor, platformMark('api'));
assert.doesNotMatch(vscode + cursor, /<img\b|connected-app-initials/);
""",
    )


def test_brand_marks_stay_visible_and_proportional_on_dark_cards(tmp_path: Path) -> None:
    _run_brand_contract(
        tmp_path,
        r"""
for (const toolkit of ['openai', 'vercel', 'intercom']) {
  const mark = platformBrandMark(toolkit);
  assert.match(mark, /^<svg\b[^>]*\bfill="#F0F3F6"/i,
    `${toolkit} must explicitly paint its otherwise-black paths for dark cards`);
  assert.doesNotMatch(mark, /fill="(?:black|#000(?:000)?)"/i);
}
for (const toolkit of ['github', 'cursor', 'linear']) {
  const mark = platformBrandMark(toolkit);
  assert.doesNotMatch(mark, /#(?:161614|26251e|222326)\b/i,
    `${toolkit} must not retain its original low-contrast dark fill`);
  assert.match(mark, /\bfill="#[0-9a-f]{6}"/i);
}
const gitlab = platformBrandMark('gitlab');
const viewBox = gitlab.match(/\bviewBox="([^"]+)"/);
assert.ok(viewBox, 'GitLab must define its icon bounds');
const [, , width, height] = viewBox[1].trim().split(/\s+/).map(Number);
assert.ok(width > 0 && height > 0);
assert.ok(width / height >= 0.8 && width / height <= 1.25,
  'GitLab must use the compact icon, not a wide wordmark shrunk into the logo slot');
""",
    )


def test_browser_runtime_does_not_treat_query_selector_as_a_collection() -> None:
    unsafe_patterns = [
        "$('[data-provider-logo]',root).forEach",
        "$('[data-copy]').forEach",
        "$('.docs-group a').forEach",
        "$('.docs-group').forEach",
        "$('[data-cap-field]',fields).forEach",
    ]
    for pattern in unsafe_patterns:
        assert pattern not in APP
