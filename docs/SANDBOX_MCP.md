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
        +----------------------------+
        |                            |
        v                            v
SandboxManager               BrowserSandboxManager
        |                            |
        +-------------+--------------+
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

### Services

- `sandbox_start_service` resumes a named sandbox, validates a pre-published port, starts the service as a detached process, and returns its provider route/public URL.

Vercel requires exposed ports to be declared when the sandbox is created. Internet Hands therefore
does not invent a post-creation `publish-port` operation: create the sandbox with `ports=[3000]`, then
start the service on port 3000. `sandbox_start_service` refuses undeclared ports.

## Live browser subsystem

The browser is a structured computer subsystem inside the sandbox, not a public DevTools endpoint.
Each named `browser_session` runs one live headless Chromium context as a detached sandbox process.
The control plane talks to it through a Unix-domain socket stored inside the sandbox with restrictive
permissions. No Chrome DevTools/CDP port is exposed publicly.

This matters for agent workflows: separate calls such as `fill`, `click`, `press`, `extract`, and
`screenshot` operate on the **same live page**. Form values, open menus, client-side state, SPA state,
active cookies, local storage, and the current DOM are not thrown away between MCP calls while the
browser daemon is alive. Requests to a named browser are serialized so concurrent calls do not race
the same page.

The persistent Chromium profile and last URL live on the sandbox filesystem. Cookies, local storage,
and profile data therefore survive a browser-daemon restart and persistent sandbox snapshot/resume.
Transient DOM state naturally ends when the browser process itself ends; after restart the daemon
restores the last URL using the persisted profile.

The browser control protocol is versioned independently inside the v0.4 package; the live-daemon
protocol is currently version 2. The runtime uses pinned Playwright 1.55.0 and a Chromium binary
under `.internet-hands/browser`. Preparation is asynchronous so a serverless control-plane request
does not need to stay open while Chromium downloads. Browser actions automatically start the named
daemon when it is not running and wait briefly for its private socket to become responsive. The
daemon is a bounded background command and therefore remains subject to the one-hour command ceiling
and the sandbox session's own TTL; a later action transparently starts a fresh daemon from the
persisted profile when needed.

Browser tools:

- `sandbox_browser_prepare` writes/installs the versioned Playwright + Chromium runtime asynchronously.
- `sandbox_browser_state` gets live URL/title state and starts the named browser when needed.
- `sandbox_browser_open` navigates the live page to a public HTTP(S) URL.
- `sandbox_browser_click` clicks a Playwright locator with optional navigation waiting.
- `sandbox_browser_fill` fills a field while preserving the resulting live DOM state.
- `sandbox_browser_press` sends a key to a located element on that same live page.
- `sandbox_browser_extract` extracts bounded text, HTML, or links from the current DOM.
- `sandbox_browser_capture` writes a screenshot of the current page to a sandbox artifact path.
- `sandbox_browser_download` waits for a locator-triggered download and saves it in the sandbox.
- `sandbox_browser_trace` reads bounded persistent console/page-error or request/response events and may clear them.
- `sandbox_browser_close` gracefully closes one named Chromium daemon and removes its private control socket.
- `sandbox_browser_screenshot` remains as a simple one-shot compatibility screenshot tool.

The manager validates explicit navigation targets with the public-URL policy. The in-guest browser
runtime also blocks obvious localhost/private/link-local targets, while the sandbox provider network
policy remains the final defense against DNS rebinding or redirects to non-public addresses.

Browser output is bounded: text/HTML extraction is limited by `max_chars`, link extraction returns at
most 200 entries, a trace call returns at most 200 events, individual event fields are clipped, and
the persisted JSONL trace files are rotated. This prevents long/noisy pages from expanding MCP
context or guest disk usage indefinitely.

### Browser workflow

```text
sandbox_browser_prepare(session_id)
        -> detached install command_id
sandbox_command(session_id, command_id, wait=true)
        -> runtime ready

sandbox_browser_open(session_id, "https://example.com", browser_session="research")
        -> named Chromium daemon auto-starts
sandbox_browser_fill(session_id, "input[name=q]", "query", browser_session="research")
sandbox_browser_press(session_id, "input[name=q]", "Enter", browser_session="research")
sandbox_browser_click(session_id, "text=Docs", browser_session="research")
sandbox_browser_extract(session_id, selector="main", mode="text", browser_session="research")
sandbox_browser_trace(session_id, kind="network", browser_session="research")
sandbox_browser_capture(session_id, output_path="artifacts/research.png", browser_session="research")
sandbox_artifact(session_id, "artifacts/research.png")
sandbox_browser_close(session_id, browser_session="research")
```

For downloads, call `sandbox_browser_download` with the locator that triggers the download, then use
`sandbox_artifact` or `sandbox_read_file` on the returned path.

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
- browser extracted text/HTML: 500,000 characters maximum per call
- browser extracted links: 200 maximum per call
- browser trace events: 200 maximum per call
- browser fill payload: 100,000 characters maximum
- browser trace files: rotated at approximately 4 MB each
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
sandbox_browser_prepare(session_id)
sandbox_browser_open(session_id, public_url, browser_session="qa", cwd="project")
sandbox_browser_fill(session_id, "input", "hello", browser_session="qa", cwd="project")
sandbox_browser_capture(session_id, output_path="artifacts/page.png", browser_session="qa", cwd="project")
sandbox_artifact(session_id, "artifacts/page.png", cwd="project")
sandbox_browser_close(session_id, browser_session="qa")
sandbox_snapshot(session_id)
```

## CI

Unit tests use fake providers and mocked HTTP transports. CI never creates Vercel sandboxes and
therefore cannot consume sandbox runtime or require Vercel credentials. The test matrix validates
supported Python versions 3.11, 3.12, and 3.13, and syntax-checks the embedded browser runtime with
Node when it is available on the runner.
