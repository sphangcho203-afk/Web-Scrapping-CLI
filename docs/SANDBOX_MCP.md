# Internet Hands Sandbox MCP

Internet Hands v0.4 adds an isolated cloud-computer plane beside the crawler/data plane.
The first provider is Vercel Sandbox, but the orchestration code depends on a provider protocol so
E2B or self-hosted Firecracker providers can be added without changing MCP tools.

## Architecture

```text
MCP client / agent
        |
        | Streamable HTTP + API key
        v
Internet Hands /mcp
        |
        v
SandboxManager
        |
        v
SandboxProvider protocol
        |
        +---- VercelSandboxProvider (v0.4)
        +---- future E2B provider
        +---- future self-hosted Firecracker provider
```

The HTTP control plane remains available at the normal Internet Hands API. The MCP transport is
mounted at `/mcp/` and is intentionally protected by the same `INTERNET_HANDS_API_KEY` used by the
REST control plane. MCP clients may send either `X-API-Key` or `Authorization: Bearer <key>`.

## Cloud-computer tools

- `sandbox_create` creates a named isolated computer with CPU, memory, TTL, and optional public ports.
- `sandbox_get` gets or resumes the active session for a named sandbox.
- `sandbox_exec` runs one executable with structured arguments, env, cwd, timeout, and optional sudo.
- `sandbox_shell` runs a shell script inside the guest VM.
- `sandbox_install` installs packages with apt, pip, or npm.
- `sandbox_git_clone` clones public HTTPS Git repositories without embedded credentials.
- `sandbox_read_file` reads UTF-8 or binary files (binary content is returned as base64).
- `sandbox_write_file` writes UTF-8 or base64 content.
- `sandbox_mkdir` creates a directory tree.
- `sandbox_browser_screenshot` installs/uses Playwright Chromium in the guest and captures a page.
- `sandbox_snapshot` snapshots the guest filesystem for later restoration.

## Authentication

On Vercel, `VercelSandboxProvider` prefers the short-lived `VERCEL_OIDC_TOKEN` supplied by the
platform. Local development can use `INTERNET_HANDS_VERCEL_TOKEN` or `VERCEL_TOKEN`.

The provider also needs the target project id. Resolution order:

1. `INTERNET_HANDS_SANDBOX_PROJECT_ID`
2. `VERCEL_PROJECT_ID`

Team id is optional and resolves from `INTERNET_HANDS_SANDBOX_TEAM_ID` then `VERCEL_TEAM_ID`.

## Network boundary

Sandboxes are created with public internet available but private/internal destinations denied at the
provider network layer. The default deny list includes loopback, RFC1918, carrier-grade NAT,
link-local/cloud metadata, multicast/reserved IPv4, IPv6 loopback, ULA, and IPv6 link-local ranges.

This means package registries, public Git hosts, and public websites work while the sandbox is not a
route into the control plane, local machine, VPC, or cloud metadata service.

## Resource policy

Default manager limits:

- command timeout: 120 seconds maximum
- tool output/file response: 1 MB maximum
- vCPUs: up to 4
- memory: up to 8 GB
- published ports: up to 8
- package install: up to 50 packages per call

The provider remains the final isolation boundary. Internet Hands does not mount host filesystems or
expose Docker-in-Docker/host sockets.

## Browser behavior

The browser tool is intentionally built inside the disposable VM. It uses Playwright Chromium via
`npx`, saves the screenshot to the guest filesystem, and returns the artifact path. Use
`sandbox_read_file` to retrieve the image as base64 when an MCP client needs the bytes.

A future browser layer can add persistent browser sessions, DOM actions, screenshots, downloads,
and console/network traces without changing the provider contract.

## CI

Unit tests use a fake provider. CI never creates Vercel sandboxes and therefore cannot consume
sandbox runtime or require Vercel credentials.
