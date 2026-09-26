# Capability fabric: first query search slice

The canonical runtime remains `src/internet_hands/tool_mcp.py`: it constructs the
tool mesh and semantic registry. The browser UI is `web/app.js` with shared CSS in
`web/cognitive-foundation.css`. `/api/public-data/{operation}` uses the existing
API key identity, credit reservation, and measured settlement. The same provider
is callable as `publicdata:search` via the mesh and `web.public.search` via the
semantic registry and MCP gateway. No backend contracts were replaced.

## Execution path

1. Validate the query, selected indexes, and result limit before credit reservation.
2. Reserve two base credits plus three per selected public index (one GET each).
3. Search selected indexes concurrently with fixed HTTPS destinations and
   redirect host guards, 1 MB response bounds, and per-index timeouts.
4. Normalize title, URL, snippet, canonical ID, collection time, and index
   endpoint. Deduplicate scholarly records on DOI, retaining both evidence entries.
5. Rank corroborated records first, then title term overlap; report partial
   errors per index without claiming that unqueried records were verified.
6. Settle on attempted network requests. No request means no request charge.

The registered sources are Wikipedia's documented Action API search, OpenAlex
works search, and Crossref works search. Keyless OpenAlex access has a shared
daily budget; this implementation cannot guarantee availability under load.
The output is scoped to these public indexes, so it is not a whole-web search.

Source contracts: [MediaWiki search](https://www.mediawiki.org/wiki/API:Search_and_discovery),
[OpenAlex API](https://help.openalex.org/api/),
[OpenAlex authentication and limits](https://help.openalex.org/api/authentication/),
[Crossref REST](https://www.crossref.org/documentation/retrieve-metadata/rest-api/).

## Extension seam

`federated_search.SearchSource` declares a fixed endpoint, query encoding, and
result normalizer. Add a documented source by implementing a normalizer and
registering it in `SOURCES`; update the allowed sources in the capability and
descriptor schemas and add a normalization/failure test. Selection, concurrency,
partial errors, DOI deduplication, evidence, and measured source attempts remain
shared. A future persistent cache must include retrieval and expiry times in
the result and expose cache hits to the execution ledger; this pass makes no
live freshness claim from stored data.

Repository evaluation via Composio found SearXNG actively maintained but
AGPL-3.0 and substantially larger than this deployment slice. Trafilatura is
Apache-2.0 and already an optional extraction dependency in `pyproject.toml`.
No third-party repository code was copied in this pass.
