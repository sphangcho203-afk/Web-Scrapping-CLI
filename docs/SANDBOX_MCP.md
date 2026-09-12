# Internet Hands Sandbox MCP

Internet Hands v0.4 adds an isolated cloud-computer plane beside the crawler/data plane. The first
provider is Vercel Sandbox, while orchestration depends on a provider protocol so E2B or self-hosted
Firecracker-style providers can be added without changing the MCP tool contract.

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

The MCP transport is mounted at `/mcp/` and is protected by the same
`INTERNET_HANDS_API_KEY` used by the REST control plane. Clients may send either `X-API-Key` or
`Authorization: Bearer <key>`.

## Cloud-computer tools

### Lifecycle

- `sandbox_create` creates a named isolated computer with CPU, memory, TTL, persistence, and optional public ports.
- `sandbox_get` gets or resumes the active session for a named sandbox.
- `sandbox_snapshot` snapshots the filesystem for later restoration; Vercel stops that session.
- `sandbox_fork` creates a new named sandbox from an existing sandbox with optional resource/port overrides.
- `sandbox_stop` stops a running session and all processes in it.
- `sandbox_delete` permanently deletes the named sandbox and its sessions. Snapshots are provider-managed separately.

### Terminal and processes

- `sandbox_exec` runs one executable with structured arguments, env, cwd, timeout, and optional sudo, then waits.
- `sandbox_shell` runs a bounded shell script inside the guest VM.
- `sandbox_start` starts a detached/background command and immediately returns its command id.
- `sandbox_command` inspects a command and can wait for it to finish.
- `sandbox_commands` lists command history for a session.
- `sandbox_command_logs` reads bounded command logs.
- `sandbox_kill` sends SIGINT, SIGTERM, or SIGKILL to a command.
- `sandbox_install` installs packages with apt, pip, or npm using structured arguments.

Foreground commands have a 120-second policy ceiling. Detached commands default to 30 minutes and
may run for up to one hour, subject to the sandbox's own provider TTL.

### Repositories, files, and artifacts

- `sandbox_git_clone` clones public HTTPS Git repositories without embedded credentials.
- `sandbox_read_file` reads UTF-8 or binary files; binary content is returned as base64.
- `sandbox_write_file` writes UTF-8 or base64 content.
- `sandbox_mkdir` creates a directory tree.
- `sandbox_artifact` retrieves a file as bounded base64 together with MIME type, byte count, and SHA-256.

Artifact and ordinary file responses are capped by the manager policy so a tool call cannot dump an
unbounded guest filesystem into MCP context.

### Services and browser

- `sandbox_start_service` resumes a named sandbox, validates a pre-published port, starts the service as a detached process, and returns its provider route/public URL.
- `sandbox_browser_screenshot` installs/uses Playwright Chromium inside the guest and saves a full-page screenshot.

Vercel requires exposed ports to be declared when the sandbox is created. Internet Hands therefore
does not invent a post-creation `publish-port` operation: create the sandbox with `ports=[3000]`, then
start the service on port 3000. `sandbox_start_service` refuses undeclared ports.

Browser execution remains inside the isolated computer. Internet Hands does **not** publish an
unauthenticated Chrome DevTools/CDP endpoint by default. Screenshots and other browser outputs are
returned through the normal artifact/file tools.

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

This allows public package registries, public Git hosts, and public websites while preventing the
sandbox from becoming a route into the control plane, local machine, VPC, or cloud metadata service.

## Resource policy

Default manager limits:

- foreground command timeout: 120 seconds maximum
- detached/background timeout: 1 hour maximum
- tool output/file/artifact response: 1 MB maximum
- vCPUs: up to 4
- memory: up to 8 GB
- published ports: up to 8
- package install: up to 50 packages per call
- process signals exposed through MCP: SIGINT, SIGTERM, SIGKILL only

The provider remains the final isolation boundary. Internet Hands does not mount host filesystems or
expose Docker-in-Docker/host sockets.

## Typical agent workflow

```text
sandbox_create(name="app", ports=[3000])
        -> session_id
sandbox_git_clone(session_id, "https://github.com/example/project.git")
sandbox_install(session_id, ["..."], manager="npm")
sandbox_exec(session_id, "npm", ["run", "build"], cwd="project")
sandbox_start_service(name="app", command="npm", args=["run", "dev"], port=3000, cwd="project")
        -> command_id + public URL
sandbox_command_logs(session_id, command_id)
sandbox_browser_screenshot(session_id, public_url)
sandbox_artifact(session_id, "artifacts/page.png")
sandbox_snapshot(session_id)
```

## CI

Unit tests use a fake provider. CI never creates Vercel sandboxes and therefore cannot consume
sandbox runtime or require Vercel credentials. The test matrix validates supported Python versions
3.11, 3.12, and 3.13.
