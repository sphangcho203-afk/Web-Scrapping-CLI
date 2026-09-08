# Security

Internet Hands processes arbitrary public HTTP(S) targets, so network-boundary mistakes matter.

## Reporting

Please report vulnerabilities privately through GitHub's security reporting features when available instead of opening a public exploit issue.

## Intended boundary

The default engine is designed for public-web research, observability, archiving, and authorized data collection. It blocks localhost and non-public IP space, validates redirects, caps response sizes, and keeps the crawler bounded.

A public deployment should additionally use authentication, quotas, outbound network policy, DNS-rebinding defenses, isolated browser workers, and audit logging.
