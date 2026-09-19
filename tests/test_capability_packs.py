from __future__ import annotations

from typing import Any

import pytest

from internet_hands.capability_packs import (
    Capability,
    CapabilityCandidate,
    CapabilityRegistry,
)
from internet_hands.tool_mesh import ToolDescriptor, ToolMesh


class CapabilityProvider:
    def __init__(self, name: str, *, fail: bool = False) -> None:
        self.name = name
        self.fail = fail

    async def status(self) -> dict[str, Any]:
        return {"configured": True, "searchable": True, "executable": True}

    async def search(self, query: str, *, limit: int = 10) -> list[ToolDescriptor]:
        return [
            ToolDescriptor(
                ref=f"{self.name}:dynamic",
                provider=self.name,
                tool_id="dynamic",
                name=query,
                side_effecting=False,
            )
        ][:limit]

    async def describe(self, tool_id: str) -> ToolDescriptor:
        return ToolDescriptor(
            ref=f"{self.name}:{tool_id}",
            provider=self.name,
            tool_id=tool_id,
            name=tool_id,
            side_effecting=False,
        )

    async def execute(
        self,
        tool_id: str,
        arguments: dict[str, Any],
        *,
        account: str | None = None,
        wait_seconds: int = 30,
        timeout_seconds: int = 60,
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        del account, wait_seconds, timeout_seconds, options
        if self.fail:
            raise RuntimeError("provider failed")
        return {
            "status": "completed",
            "data": {"tool": tool_id, "arguments": arguments, "provider": self.name},
        }

    async def job_status(self, job_id: str, *, wait_seconds: int = 0) -> dict[str, Any]:
        return {"id": job_id, "wait_seconds": wait_seconds}

    async def result_page(
        self, result_id: str, *, offset: int = 0, limit: int = 100
    ) -> dict[str, Any]:
        return {"id": result_id, "offset": offset, "limit": limit}


@pytest.mark.asyncio
async def test_capability_falls_back_and_maps_arguments() -> None:
    mesh = ToolMesh(
        [CapabilityProvider("preferred", fail=True), CapabilityProvider("fallback")]
    )
    registry = CapabilityRegistry(
        mesh,
        [
            Capability(
                id="game.player.lookup",
                name="Player lookup",
                description="Lookup",
                pack="game",
                tags=("game",),
                candidates=(
                    CapabilityCandidate(
                        provider="preferred",
                        ref="preferred:lookup",
                        priority=10,
                    ),
                    CapabilityCandidate(
                        provider="fallback",
                        ref="fallback:lookup",
                        priority=20,
                        argument_map={"zone": "server"},
                    ),
                ),
            )
        ],
    )

    result = await registry.execute(
        "game.player.lookup", {"id": "123", "zone": "456"}
    )
    assert result["selected"] == "fallback:lookup"
    assert [attempt["status"] for attempt in result["attempts"]] == ["failed", "completed"]
    assert result["execution"]["data"]["arguments"] == {"id": "123", "server": "456"}


@pytest.mark.asyncio
async def test_capability_search_candidate_resolves() -> None:
    mesh = ToolMesh([CapabilityProvider("catalog")])
    registry = CapabilityRegistry(
        mesh,
        [
            Capability(
                id="game.hero.list",
                name="Hero list",
                description="Heroes",
                pack="game",
                tags=("hero",),
                candidates=(
                    CapabilityCandidate(
                        provider="catalog", search="heroes list", priority=10
                    ),
                ),
            )
        ],
    )
    resolved = await registry.resolve("game.hero.list")
    assert resolved["resolved"][0]["ref"] == "catalog:dynamic"
    assert resolved["resolved"][0]["available"] is True


@pytest.mark.asyncio
async def test_capability_dry_run_does_not_execute_provider() -> None:
    mesh = ToolMesh([CapabilityProvider("one", fail=True)])
    registry = CapabilityRegistry(
        mesh,
        [
            Capability(
                id="game.lookup",
                name="Lookup",
                description="Lookup",
                pack="game",
                tags=("game",),
                candidates=(
                    CapabilityCandidate(provider="one", ref="one:lookup", priority=10),
                ),
            )
        ],
    )
    result = await registry.execute("game.lookup", {"id": "1"}, dry_run=True)
    assert result["selected"] == "one:lookup"
    assert result["execution"]["status"] == "dry_run"


def test_capability_listing_filters_pack_and_query() -> None:
    mesh = ToolMesh([CapabilityProvider("one")])
    registry = CapabilityRegistry(
        mesh,
        [
            Capability(
                id="mlbb.hero.list",
                name="MLBB Hero List",
                description="Heroes",
                pack="mlbb",
                tags=("hero",),
                candidates=(CapabilityCandidate(provider="one", ref="one:a"),),
            ),
            Capability(
                id="weather.current",
                name="Current Weather",
                description="Weather",
                pack="weather",
                tags=("weather",),
                candidates=(CapabilityCandidate(provider="one", ref="one:b"),),
            ),
        ],
    )
    result = registry.list(query="hero", pack="mlbb")
    assert [item["id"] for item in result["capabilities"]] == ["mlbb.hero.list"]


class SideEffectProvider(CapabilityProvider):
    def __init__(self, name: str) -> None:
        super().__init__(name)
        self.last_account: str | None = None

    async def describe(self, tool_id: str) -> ToolDescriptor:
        return ToolDescriptor(
            ref=f"{self.name}:{tool_id}",
            provider=self.name,
            tool_id=tool_id,
            name=tool_id,
            side_effecting=True,
        )

    async def execute(
        self,
        tool_id: str,
        arguments: dict[str, Any],
        *,
        account: str | None = None,
        wait_seconds: int = 30,
        timeout_seconds: int = 60,
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.last_account = account
        return await super().execute(
            tool_id,
            arguments,
            account=account,
            wait_seconds=wait_seconds,
            timeout_seconds=timeout_seconds,
            options=options,
        )


@pytest.mark.asyncio
async def test_write_capability_requires_explicit_side_effect_gate() -> None:
    mesh = ToolMesh([SideEffectProvider("composio")])
    capability = Capability(
        id="messaging.send",
        name="Send message",
        description="Send",
        pack="connected",
        tags=("messaging",),
        read_only=False,
        candidates=(
            CapabilityCandidate(
                provider="composio",
                ref="composio:TELEGRAM_SEND_MESSAGE",
                when={"platform": "telegram"},
                argument_map={"target": "chat_id", "message": "text"},
                passthrough_arguments=False,
            ),
        ),
    )
    registry = CapabilityRegistry(mesh, [capability])

    with pytest.raises(PermissionError, match="allow_side_effects"):
        await registry.execute(
            "messaging.send",
            {"platform": "telegram", "target": "123", "message": "hello"},
        )


@pytest.mark.asyncio
async def test_write_capability_routes_by_condition_maps_args_and_account() -> None:
    provider = SideEffectProvider("composio")
    mesh = ToolMesh([provider])
    capability = Capability(
        id="messaging.send",
        name="Send message",
        description="Send",
        pack="connected",
        tags=("messaging",),
        read_only=False,
        candidates=(
            CapabilityCandidate(
                provider="composio",
                ref="composio:TELEGRAM_SEND_MESSAGE",
                priority=10,
                when={"platform": "telegram"},
                argument_map={"target": "chat_id", "message": "text"},
                passthrough_arguments=False,
            ),
            CapabilityCandidate(
                provider="composio",
                ref="composio:DISCORDBOT_CREATE_MESSAGE",
                priority=10,
                when={"platform": "discord"},
                argument_map={"target": "channel_id", "message": "content"},
                passthrough_arguments=False,
            ),
        ),
    )
    registry = CapabilityRegistry(mesh, [capability])
    result = await registry.execute(
        "messaging.send",
        {
            "platform": "discord",
            "target": "chan-1",
            "message": "hello",
            "provider_noise": "drop-me",
        },
        account="work",
        allow_side_effects=True,
    )
    assert result["selected"] == "composio:DISCORDBOT_CREATE_MESSAGE"
    assert result["attempts"][0]["status"] == "skipped"
    assert result["execution"]["data"]["arguments"] == {
        "channel_id": "chan-1",
        "content": "hello",
    }
    assert provider.last_account == "work"


def test_default_capabilities_include_connected_plane() -> None:
    from internet_hands.capability_packs import build_default_capabilities

    capabilities = {item.id: item for item in build_default_capabilities()}
    for capability_id in (
        "browser.navigate",
        "browser.task.status",
        "automation.workflow",
        "automation.workflow.status",
        "messaging.send",
        "code.execute",
    ):
        assert capability_id in capabilities
    assert capabilities["messaging.send"].read_only is False
    assert capabilities["messaging.send"].input_schema["required"] == [
        "platform",
        "target",
        "message",
    ]
