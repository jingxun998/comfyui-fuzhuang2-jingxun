# Changelog

All notable changes are documented here.

## [0.1.0] - 2026-08-11

### Added

- Public source for all seven ComfyUI nodes and both utility modules.
- Safe example configuration, privacy policy, security policy, threat model,
  contribution rules, automated tests, CI, CodeQL, Dependabot, and tagged-release automation.
- Request/response/image limits, image validation, error redaction, redirect blocking,
  explicit custom-endpoint trust, and bounded in-memory caching.

### Changed

- Default image model migrated from the retired preview identifier to
  `gemini-3.1-flash-image`.
- Official requests now use the stable `v1` endpoint and place
  `responseModalities` inside `generationConfig`; unsupported request fields
  from other API surfaces are not sent to `generateContent`.
- Existing node class names, Chinese input fields, functions, outputs, and
  categories remain compatible with the original workflows.
- Unused legacy `google-generativeai` dependency removed.

### Security

- Removed the committed local credential configuration from the release tree.
- Official Google HTTPS endpoint is the only destination enabled by default.
- Custom endpoints now require both explicit opt-in and a hostname allowlist.
