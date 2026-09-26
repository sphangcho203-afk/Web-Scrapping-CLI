import json

import pytest
from test_public_data_provider import fetched

from internet_hands import public_data_provider
from internet_hands.capability_economics import estimate_call, settle_measured_cost
from internet_hands.capability_packs import CapabilityRegistry
from internet_hands.execution_meter import (
    execution_usage_snapshot,
    reset_execution_meter,
    start_execution_meter,
)
from internet_hands.tool_mesh import ToolMesh


@pytest.mark.parametrize("arguments", [
    {"query": "x"}, {"query": "data", "sources": []},
    {"query": "data", "sources": ["wikipedia", "wikipedia"]},
    {"query": "data", "sources": ["unknown"]},
    {"query": "data", "limit": True}, {"query": "data", "limit": 11},
    {"query": "data", "url": "https://example.com"},
])
def test_search_rejects_unbounded_or_invalid_calls(arguments):
    with pytest.raises(ValueError):
        public_data_provider.request_budget("search", arguments)
    assert not estimate_call("mesh_execute", {"ref": "publicdata:search", "arguments": arguments}, "free").allowed


async def test_search_deduplicates_dois_preserves_evidence_and_settles_attempts(monkeypatch):
    requests = []

    async def fetch(url, **kwargs):
        requests.append(url)
        assert kwargs["url_guard"](url)
        assert not kwargs["url_guard"]("https://outside.example/results")
        if "openalex.org" in url:
            data = {"results": [{"id": "https://openalex.org/W1", "title": "Agent research",
                                  "doi": "https://doi.org/10.1234/PAPER", "publication_date": "2026-09-01",
                                  "primary_location": {"source": None}}]}
        elif "crossref.org" in url:
            data = {"message": {"items": [{"DOI": "10.1234/paper", "title": ["Agent research"], "publisher": "Press"}]}}
        else:
            data = {"query": {"search": [{"title": "Agent research", "pageid": 123,
                                           "snippet": "<span>Research</span> overview"}]}}
        return fetched(json.dumps(data), "application/json", url)

    monkeypatch.setattr(public_data_provider, "fetch_url", fetch)
    args = {"query": "agent research", "sources": ["openalex", "crossref", "wikipedia"], "limit": 5}
    call = {"ref": "publicdata:search", "arguments": args}
    quote = estimate_call("mesh_execute", call, "free")
    assert quote.allowed and quote.credits == 11
    token = start_execution_meter()
    try:
        result = await ToolMesh([public_data_provider.PublicDataProvider()]).execute(call["ref"], args)
        usage = execution_usage_snapshot()
    finally:
        reset_execution_meter(token)
    assert result["status"] == "completed"
    data = result["data"]
    assert data["result_count"] == 2 and not data["partial"]
    assert data["results"][0]["sources"] == ["openalex", "crossref"]
    assert len(data["results"][0]["evidence"]) == 2
    assert data["results"][0]["canonical_id"] == "doi:10.1234/paper"
    assert data["results"][1]["snippet"] == "Research overview"
    assert len(requests) == usage["counters"]["public_data_requests"] == 3
    assert settle_measured_cost("mesh_execute", call, "free", reserved_credits=quote.credits, execution_usage=usage) == 11


async def test_search_source_failure_is_partial_and_charged_as_attempt(monkeypatch):
    async def fetch(url, **kwargs):
        if "crossref.org" in url:
            raise RuntimeError("unavailable")
        return fetched('{"results": []}', "application/json", url)

    monkeypatch.setattr(public_data_provider, "fetch_url", fetch)
    args = {"query": "public data", "sources": ["openalex", "crossref"]}
    token = start_execution_meter()
    try:
        result = await ToolMesh([public_data_provider.PublicDataProvider()]).execute("publicdata:search", args)
        usage = execution_usage_snapshot()
    finally:
        reset_execution_meter(token)
    assert result["status"] == "completed" and result["data"]["partial"]
    assert result["data"]["errors"][0]["source"] == "crossref"
    assert usage["counters"]["public_data_requests"] == 2


async def test_search_all_sources_unavailable_reports_failure(monkeypatch):
    async def fetch(url, **kwargs):
        raise RuntimeError("offline")

    monkeypatch.setattr(public_data_provider, "fetch_url", fetch)
    result = await ToolMesh([public_data_provider.PublicDataProvider()]).execute("publicdata:search", {"query": "agent", "sources": ["wikipedia"]})
    assert result["status"] == "failed"
    assert result["data"]["sources_attempted"] == ["wikipedia"]


async def test_semantic_search_is_registered_with_input_and_output_schemas(monkeypatch):
    async def fetch(url, **kwargs):
        return fetched('{"query":{"search":[{"pageid":42,"title":"Agent"}]}}', "application/json", url)

    monkeypatch.setattr(public_data_provider, "fetch_url", fetch)
    registry = CapabilityRegistry(ToolMesh([public_data_provider.PublicDataProvider()]),
                                  public_data_provider.build_public_data_capabilities())
    monkeypatch.setattr("internet_hands.tool_mcp.get_capability_registry", lambda: registry)
    capability = registry.list(query="federated public search")["capabilities"][0]
    assert capability["id"] == "web.public.search"
    assert capability["output_schema"]["properties"]["partial"]["type"] == "boolean"
    args = {"query": "agent", "sources": ["wikipedia"]}
    quote = estimate_call("mesh_capability_execute", {"capability": "web.public.search", "arguments": args}, "free")
    assert quote.allowed
    result = await registry.execute("web.public.search", args)
    assert result["selected"] == "publicdata:search"
    assert result["execution"]["data"]["results"][0]["title"] == "Agent"
