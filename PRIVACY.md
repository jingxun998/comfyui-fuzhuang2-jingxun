# Privacy and data flow

## What leaves the computer

When a user executes one of the seven nodes, the plugin sends the node's prompt
and the selected input image(s) to the configured Gemini-compatible endpoint.
Depending on the workflow, an image may contain a person's face, body, clothing,
background, product photography, or other personal or commercially sensitive data.

The API key is sent as an authentication header by default. A trusted custom
provider may use a different header or query parameter only after the user
explicitly enables and allowlists that provider. Provider-side processing,
retention, and logging are controlled by the selected service and its current
account settings and terms. This plugin does not add an unsupported request
field to claim that Google `generateContent` storage has been disabled.

## What this plugin stores

The plugin contains no telemetry or analytics. It does not intentionally upload
files that were not supplied to the running node. Generated image bytes may be
kept temporarily in an in-memory LRU cache when a fixed seed is used. The cache
has item and total-byte limits and disappears when the ComfyUI process exits.
The plugin itself does not write generated images to disk; downstream ComfyUI
nodes may do so.

## Provider responsibility

Remote processing is governed by the selected provider's terms, retention rules,
regional availability, and privacy policy. Do not send images that you are not
authorized to process. A third-party proxy receives the same prompts, images,
and credential material required by its authentication design, so enable one
only after reviewing and trusting its operator.
