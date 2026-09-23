from internet_hands.playground_api import _rank_evidence, _synthesize_evidence

def test_rank_evidence_prefers_query_coverage():
    evidence=[{"url":"https://a.test","title":"Other","text":"unrelated material","search_rank":1},{"url":"https://b.test","title":"Pricing","text":"Acme pricing is 20 dollars for the business plan.","search_rank":2}]
    ranked=_rank_evidence("Acme business pricing", evidence)
    assert ranked[0]["url"] == "https://b.test"
    assert ranked[0]["relevance_score"] > ranked[1]["relevance_score"]

def test_synthesis_emits_source_citations():
    evidence=[{"url":"https://a.test","title":"Acme pricing","text":"Acme business pricing starts at twenty dollars per month. This plan includes exports and monitoring.","search_rank":1}]
    result=_synthesize_evidence("Acme business pricing", evidence)
    assert result["findings"][0]["citation"] == 1
    assert result["findings"][0]["url"] == "https://a.test"
    assert result["sources"][0]["citation"] == 1
