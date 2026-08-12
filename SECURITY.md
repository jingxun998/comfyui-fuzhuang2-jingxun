# Security policy

## Supported version

Security fixes are made against the latest tagged release and the `main` branch.
The first maintained release line is `0.1.x`.

## Reporting a vulnerability

Please use **GitHub → Security → Report a vulnerability** so credentials,
proof-of-concept details, and affected images are not exposed in a public issue.
If private vulnerability reporting is unavailable, open a public issue that asks
the maintainer to establish a private contact channel, but do not include the
secret or exploit details.

A useful report includes:

- affected commit or release;
- the node and configuration involved;
- the expected and observed behavior;
- the smallest safe reproduction;
- whether images, prompts, credentials, local files, or network access are affected.

Never submit a live API key. Revoke or rotate an exposed credential before reporting it.

## Security boundaries

This project is a ComfyUI custom-node package, so its Python code executes inside
the user's ComfyUI process. The maintained code does not invoke a shell, install
packages at runtime, use `eval`/`exec`, delete user files, or scan the filesystem.
It does send selected images and prompts to a configured remote API when a node is
executed.

Secure defaults include:

- Google's official HTTPS hostname is the only network destination enabled by default;
- a custom endpoint requires process-level opt-in and a hostname allowlist;
- redirects are blocked;
- inherited HTTP proxy variables are ignored unless explicitly enabled;
- request, response, image-byte, and image-pixel limits are enforced;
- common credential fields are redacted from displayed errors;
- local credential files are excluded from Git.

See `docs/THREAT_MODEL.md` for the full model and remaining trust assumptions.
