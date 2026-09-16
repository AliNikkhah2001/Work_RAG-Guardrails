# Business guardrail policies (versioned, git-backed)

Drop-in folder for business-specific guardrail prompts. Each policy is a YAML
file; the loader (`src/work_rag_guardrails/policies.py`) reads the pinned
version and feeds the prompts to the LLM judge (input/output stages) and to
the dashboard (`policies/` stats + terminated-sample review).

## File convention

`policies/<domain>-v<semver>.yaml`, e.g. `ics-credit-v1.0.0.yaml`.
Only the version pinned in `policies/active.yaml` is enforced; older versions
stay in git history for audit. Ship a new version by adding a file + moving
the pin — never edit a released version in place.

## Schema (per file)

```yaml
id: ics-credit            # stable domain id
version: 1.0.0            # semver, unique per file
stage: [input, output]    # stages this policy judges
categories:               # business categories (free-form, kebab-case)
  - id: ungrounded-claim
    title: "ادعای بدون منبع درباره امتیاز"
    prompt: |-
      <judge instruction, Persian or English; receives {{text}} and {{signals}}>
    refusal: " BER اساس..."   # user-facing refusal (Persian)
    examples:             # few-shot + regression battery
      - text: "..."
        verdict: block
        why: "..."
      - text: "..."
        verdict: allow
        why: "..."
```

`{{text}}` = candidate text, `{{signals}}` = deterministic detector hits
rendered as evidence ("we found X — this MAY be a violation, you decide").
Judge must answer with a final line `VERDICT: allow|block` + `CATEGORY: <id>`.

## Terminated samples

Blocked texts land in the guard event log (dashboard `Events` tab) with
`policy_id/policy_version/category/stage/model`, plus aggregate
percentages and plots (`Stats` tab). Nothing here stores PII in cleartext —
national IDs / Sheba are masked before logging (see PII rule).
