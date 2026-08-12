# Threat model

## Scope

This model covers the maintained Python source, its dependency declarations,
configuration paths, release artifacts, and third-party contributions. It does
not claim to secure ComfyUI itself, the operating system, the configured remote
provider, or arbitrary unreviewed forks.

## Assets

- user images, including faces, bodies, clothing, and backgrounds;
- commercial product imagery and prompts;
- Gemini or proxy API credentials;
- the integrity and availability of the ComfyUI host process;
- the integrity of source, dependencies, tags, and release archives.

## Trust boundaries

```text
ComfyUI workflow and user images
            │
            ▼
This custom node (Python in the ComfyUI process)
            │
            ├── local environment / ignored config / in-memory cache
            │
            ▼
Official Google API or an explicitly trusted custom endpoint
            │
            ▼
Remote JSON and encoded image response
```

## Primary threats and controls

| Threat | Consequence | Control |
|---|---|---|
| A checked-in config redirects traffic | Images and keys reach an attacker | Custom host requires process-level opt-in plus hostname allowlist |
| Redirect after authentication | Credentials or images are forwarded | HTTP redirects are disabled |
| Inherited hostile proxy variables | Requests are intercepted | Environment proxy use is off by default |
| Secret committed to Git | Credential reuse and account abuse | Real config/key files are ignored; repository validator scans common secret patterns |
| Malicious or compromised dependency | Code executes in the host process | Small direct dependency set, bounded versions, Dependabot, dependency review by maintainers |
| Malicious pull request | New shell/file/network behavior | CI, CodeQL, contribution rules, human review, explicit network-boundary tests |
| Oversized or malformed remote response | Memory exhaustion or image parser failure | Response-byte, decoded-byte, pixel, format, and decompression-bomb checks |
| Verbose remote error | Credential or sensitive response leakage | Error extraction and credential redaction; raw JSON is not displayed |
| Source/release drift | Users install code different from reviewed source | Release archive is built deterministically from the tagged tree and validated in CI |
| Prompt/image injection changes model output | Incorrect or misleading image | Model output never becomes shell, file, or tool instructions; user reviews visual output |

## Residual risks

- A user who explicitly trusts a custom provider is trusting that provider with
  the transmitted images, prompts, and authentication material.
- Python dependencies and the remote model provider remain external supply-chain
  components.
- Generative output can be inaccurate, biased, altered beyond the prompt, or
  rejected by provider safety systems.
- A compromised ComfyUI host or operating system can read process memory and
  environment variables; this plugin cannot defend against a fully compromised host.
- DNS and TLS security ultimately depend on the operating system, certificate
  store, and network environment.

## CI and release supply chain

GitHub Actions are pinned to immutable full commit SHAs. Dependabot may propose action updates, but each update remains subject to review and CI. Release archives are built deterministically from tagged source rather than committed as a second source tree.
