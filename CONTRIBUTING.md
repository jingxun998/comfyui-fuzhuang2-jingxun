# Contributing

Contributions are welcome when they preserve the project's narrow purpose:
reusable Gemini-powered fashion image workflows for ComfyUI.

## Before opening a pull request

1. Explain the user problem and the affected node.
2. Preserve existing node class names, Chinese field names, return types, and
   workflow links unless the change includes a documented migration path.
3. Add or update tests for every behavior change.
4. Run:

   ```bash
   python scripts/validate_repository.py
   python -m pytest -q
   ```

5. Update `README.md`, `CHANGELOG.md`, and privacy/security documentation when
   network behavior, credentials, data flow, or dependencies change.

## Security requirements

Runtime code must not:

- use `eval` or `exec`;
- run shell commands or install packages dynamically;
- introduce an undisclosed network destination;
- read unrelated local files or environment variables;
- log API keys, authorization headers, raw personal images, or full remote error bodies;
- ship minified, obfuscated, or generated binary-only source.

A new custom endpoint or authentication path must be explicit, deny-by-default,
covered by tests, and described in `PRIVACY.md` and `docs/THREAT_MODEL.md`.

## Pull request scope

Keep changes reviewable. Separate a security fix, dependency update, refactor,
and new user-facing feature when they can be reviewed independently.
