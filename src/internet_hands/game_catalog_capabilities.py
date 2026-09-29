from __future__ import annotations

from .capability_packs import Capability, CapabilityCandidate


def build_game_catalog_capabilities() -> list[Capability]:
    return [
        Capability(
            id="games.catalog.search",
            name="Multi-provider video game catalog search",
            description=(
                "Search documented game metadata catalogs through IGDB and RAWG with "
                "normalized query and result limits."
            ),
            pack="gaming",
            tags=("gaming", "games", "catalog", "metadata", "igdb", "rawg"),
            candidates=(
                CapabilityCandidate(
                    provider="igdb",
                    ref="igdb:search-games",
                    priority=5,
                    passthrough_arguments=True,
                ),
                CapabilityCandidate(
                    provider="rawg",
                    ref="rawg:search-games",
                    priority=10,
                    passthrough_arguments=True,
                ),
            ),
            input_schema={
                "type": "object",
                "required": ["query"],
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 40},
                },
            },
        ),
        Capability(
            id="games.platform.search",
            name="Gaming platform catalog search",
            description="Search documented platform catalogs through IGDB and RAWG.",
            pack="gaming",
            tags=("gaming", "platforms", "catalog", "igdb", "rawg"),
            candidates=(
                CapabilityCandidate(
                    provider="igdb",
                    ref="igdb:search-platforms",
                    priority=5,
                    passthrough_arguments=True,
                ),
                CapabilityCandidate(
                    provider="rawg",
                    ref="rawg:platforms-search",
                    priority=10,
                    passthrough_arguments=True,
                ),
            ),
            input_schema={
                "type": "object",
                "required": ["query"],
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 40},
                },
            },
        ),
        Capability(
            id="games.developer.search",
            name="Game developer catalog search",
            description="Search RAWG's documented game developer/studio catalog.",
            pack="gaming",
            tags=("gaming", "developers", "studios", "catalog", "rawg"),
            candidates=(
                CapabilityCandidate(
                    provider="rawg",
                    ref="rawg:developers-search",
                    priority=5,
                    passthrough_arguments=True,
                ),
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 40},
                },
            },
        ),
    ]
