# Intern task — reword metric descriptions

Replace three metric descriptions in `demo/full-stack-fastapi-template/backend/app/core/metrics/registry.py` (currently lines 145–185). Keep the `display_name`, `name`, and everything else unchanged — only swap the `description` strings.

## `documents_consulted` (~line 149)

Old:
```
Distinct V2 documents the Taskforce hooks surfaced to the agent in the window. Each match returned by POST /v2/taskforce/discover counts once; the discover endpoint is fired automatically by the UserPromptSubmit hook (TF-176).
```

New:
```
Memory documents Taskforce surfaced to your agents this period.
```

## `avoided_rediscovery` (~line 162)

Old:
```
Tokens Taskforce kept the agent from having to re-derive. For each consultation, this is max(0, document.rediscovery_cost - summary_read). Rediscovery cost is a structural estimate (commands + files inspected + decisions + sections) capped at 50k tokens per doc. v1 coefficients are round numbers and will be tuned from real consult data.
```

New:
```
Tokens your agents didn't have to spend rediscovering work the team already did.
```

## `avoided_rediscovery_usd` (~line 177)

Old:
```
USD value of avoided_rediscovery, priced at the pricing snapshot effective at consultation time. Defaults to claude-opus-4-7 rates when the hook does not declare the agent's model.
```

New:
```
Dollar value of those skipped tokens at current model pricing.
```

## How to ship

Branch off `main`, single commit, PR titled `Reword metric descriptions for non-engineer readers.` No test changes needed; descriptions aren't asserted on.
