from __future__ import annotations

import re
from dataclasses import dataclass


_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}$")
_PACKAGE_RE = re.compile(r"^[A-Za-z0-9_.+@/:=-]{1,160}$")

PUBLIC_NETWORK_DENY_CIDRS = [
    "0.0.0.0/8",
    "10.0.0.0/8",
    "100.64.0.0/10",
    "127.0.0.0/8",
    "169.254.0.0/16",
    "172.16.0.0/12",
    "192.0.0.0/24",
    "192.168.0.0/16",
    "224.0.0.0/4",
    "240.0.0.0/4",
    "::1/128",
    "fc00::/7",
    "fe80::/10",
]


@dataclass(frozen=True, slots=True)
class SandboxLimits:
    max_command_timeout_ms: int = 120_000
    max_output_bytes: int = 1_000_000
    max_vcpus: int = 4
    max_memory_mb: int = 8192
    max_ports: int = 8


def validate_name(name: str) -> str:
    value = name.strip().lower()
    if not _NAME_RE.fullmatch(value):
        raise ValueError("sandbox name must be URL-safe and 1-63 characters")
    return value


def validate_resources(vcpus: int, memory_mb: int, limits: SandboxLimits) -> None:
    if not 1 <= vcpus <= limits.max_vcpus:
        raise ValueError(f"vcpus must be between 1 and {limits.max_vcpus}")
    if not 512 <= memory_mb <= limits.max_memory_mb:
        raise ValueError(f"memory_mb must be between 512 and {limits.max_memory_mb}")


def validate_ports(ports: list[int], limits: SandboxLimits) -> list[int]:
    if len(ports) > limits.max_ports:
        raise ValueError(f"at most {limits.max_ports} ports may be published")
    result: list[int] = []
    for port in ports:
        if not 1 <= int(port) <= 65535:
            raise ValueError("ports must be between 1 and 65535")
        if int(port) not in result:
            result.append(int(port))
    return result


def validate_timeout_ms(timeout_ms: int, limits: SandboxLimits) -> int:
    if not 100 <= timeout_ms <= limits.max_command_timeout_ms:
        raise ValueError(
            f"command timeout must be between 100 and {limits.max_command_timeout_ms} ms"
        )
    return timeout_ms


def validate_packages(packages: list[str]) -> list[str]:
    if not packages or len(packages) > 50:
        raise ValueError("packages must contain between 1 and 50 entries")
    cleaned: list[str] = []
    for package in packages:
        package = package.strip()
        if not _PACKAGE_RE.fullmatch(package) or package.startswith("-"):
            raise ValueError(f"invalid package name: {package!r}")
        cleaned.append(package)
    return cleaned


def public_network_policy() -> dict[str, object]:
    return {
        "mode": "allow-all",
        "deniedCIDRs": list(PUBLIC_NETWORK_DENY_CIDRS),
    }
