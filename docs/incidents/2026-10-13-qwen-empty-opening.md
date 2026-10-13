# Qwen empty opening, 2026-10-13

Production used model ID `Qwen` at `https://openclaudeapi.xyz/v1`. The ID was
confirmed by the authenticated models endpoint. Short requests and the old
preflight passed, but opening generation returned no visible content with
`finish_reason=length`; retries exhausted larger budgets or timed out.

A reproduction using the public prologue template and synthetic station facts
returned zero content and 2,920 reasoning tokens. A top-level
`enable_thinking: false` did not change that. The same request with the following
extra body returned 2,054 visible characters, zero reasoning tokens, and finished
normally in approximately 10 seconds:

```json
{"chat_template_kwargs": {"enable_thinking": false}}
```

This parameter was applied to both endpoint profiles after a production backup.
It is specific to this gateway's Qwen deployment; other vendors may require
different switches. Do not assume a top-level thinking flag is equivalent.

Endpoint preflight now tests the actual prologue template with synthetic facts
and the standard opening budget before testing the short narrative stream.
An empty opening cannot produce a successful preflight. Budget exhaustion also
reports a thinking-mode hint for Qwen. Separate fixes reject empty streams and
translate streaming transport failures into engine errors so fallback can run.

Validation uses mocked regression tests and live synthetic requests. No player
save content is required for these probes.
