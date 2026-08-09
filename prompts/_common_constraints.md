---
role: _common_constraints
version: v1
---
## OUTPUT CONTRACT (mandatory)

- Return ONLY a single JSON object. No prose, no markdown fences, no explanation.
- Never invent entity ids. Use only ids that appear in the provided context.
- Never assert world facts that are not present in the provided context.
- Numeric fields must stay inside their documented ranges.
- If you cannot comply, return the documented fallback object for your role.
