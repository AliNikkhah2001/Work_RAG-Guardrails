# Work RAG Guardrails

NeMo Guardrails boundary for the Work Credit RAG platform.

> **Status:** ✅ **IMPLEMENTED AND LIVE** on Vast.ai (`vast-gemma4-migration`, commit `6ce319f`). Deterministic Persian rails + risk scoring + semantic interface (v2).

## Responsibility

This component owns policy enforcement around the self-hosted Gemma generation service. It does not own retrieval, conversation orchestration, the frontend, or model serving.

Provides:
- Deterministic input/output checks before retrieval and generation
- NeMo Guardrails configuration with auditable Colang policy set
- OpenAI-compatible chat gateway that calls Gemma :18000
- Structured decisions and stable refusal responses
- Health and readiness endpoints

## API Contract

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/health` | Process health |
| `GET` | `/ready` | NeMo config + upstream Gemma readiness |
| `POST` | `/v1/rails/check` | Run named input or output policy stage |
| `POST` | `/v1/chat/completions` | OpenAI-compatible guarded Gemma generation |

### Rail Check Request

```json
{
  "stage": "input",
  "text": "سلام",
  "request_id": "t"
}
```

### Rail Check Response

```json
{
  "allowed": true,
  "categories": [],
  "reason": null
}
```

Blocked example:
```json
{
  "allowed": false,
  "categories": ["hate"],
  "reason": "پاسخ حاوی محتوای نامناسب است. (hate:حرامزاده)"
}
```

### Guarded Generation Request

```json
{
  "model": "unsloth/gemma-4-31B-it-GGUF:UD-Q4_K_XL",
  "messages": [{"role": "user", "content": "اعتبارسنجی چیست؟"}],
  "temperature": 0.2,
  "max_tokens": 512
}
```

## Configuration

| Variable | Default | Production |
|----------|---------|------------|
| `GUARDRAILS_HOST` | `0.0.0.0` | `0.0.0.0` |
| `GUARDRAILS_PORT` | 8200 | 8200 |
| `UPSTREAM_LLM_BASE_URL` | `http://127.0.0.1:9000/v1` | `http://127.0.0.1:18000/v1` (via `LLM_BASE_URL` alias) |
| `UPSTREAM_LLM_MODEL` | `gemma-4-31b` | `unsloth/gemma-4-31B-it-GGUF:UD-Q4_K_XL` |
| `UPSTREAM_LLM_API_KEY` | `sk-local-dev` | `sk-local-dev` |
| `LLM_BASE_URL` | (alias) | `http://127.0.0.1:18000/v1` |
| `LLM_MODEL` | (alias) | `unsloth/gemma-4-31B-it-GGUF:UD-Q4_K_XL` |

**Note:** Config default `UPSTREAM_LLM_BASE_URL=9000` is for H200 `server-setup` (manager gateway). Vast production overrides via `LLM_BASE_URL` alias to Gemma :18000.

## Pipeline Stages

### Input Rails (stage=input)

| Check | Method | Threshold | Notes |
|-------|--------|-----------|-------|
| Empty/Oversize | Deterministic | — | Configurable limits |
| Prompt Injection | Colang + deterministic | — | "دان" word-boundary jailbreak |
| HurtLex Persian | `hurtlex_fa_conservative.json` | — | **19-lemma allowlist** (see below) |
| Profanity Persian | `persian_swear.json` | `len>2` | Fixes `ان` (len 2) false positive |
| Out-of-Scope | Deterministic | — | Non-credit topics |
| PII Detection | Regex + NER | 0.90 | Persian patterns |
| Injection Risk | Heuristic | 0.85 | — |

### Output Rails (stage=output)

| Check | Model | Threshold | Notes |
|-------|-------|-----------|-------|
| HurtLex + Allowlist | Deterministic | — | Same 19 lemmas |
| Profanity | `persian_swear.json` | `len>2` | — |
| Toxicity | Ghadeer mmBERT | 0.80 | F1 0.94 Persian |
| Hate Speech | Ghadeer mmBERT | 0.80 | F1 0.94 Persian |
| Intent Classification | Ghadeer mmBERT | — | Semantic interface |
| Secret/PII Leak | Regex | 0.90 | API keys, tokens |

## HurtLex Persian Allowlist (19 Lemmas)

| Lemma | Domain | Evidence |
|-------|--------|----------|
| حذف | Credit | `درخواست حذف سابقه منفی قدیمی` |
| بخشی | Credit | `بخشی از اطلاعات` |
| تأمین مالی | Credit | Core term `تسهیلات بانکی` |
| اشتغال | Credit | `اشتغال و سابقه بیمه` |
| پست | Credit | `پست سازمانی` |
| مصرف | Credit | `گزارش‌های مصرف` |
| هدف | Credit | `هدف از دریافت تسهیلات` |
| نادرست | Credit | `اطلاعات نادرست را اصلاح` |
| پستی | Credit | KB chunk, polite greeting |
| مهم | Credit | `مهم است` flagged on `جدول نوع تماس` |
| ضعیف | Credit | 6 answers with `رتبه ضعیف` |
| خسته | Social | `خسته نباشید` greeting |
| شرح | Credit | `شرح` = description in reports |
| دسته | Credit | `دسته‌بندی` = category |
| جزئی | Credit | `جزئی` = partial/minor |
| ناشی | Credit | `ناشی از` = resulting from |
| خوشحال | Social | Positive sentiment |
| سخت | General | `سخت` = difficult |
| پلیس | Credit | `سوابق پلیس` credit data source |

**Policy:** Allowlisted for both input and output HurtLex checks on exact-word match. Profanity/PII/secret remain strict.

**File:** `kb/hurtlex_allowlist.json` (with evidence object)

## Risk Scoring & Semantic Interface (v2)

- **Risk Scorer** (`risk/scorer.py`): PII 0.90, injection 0.85, toxicity/hate 0.80
- **Semantic Toxicity/Hate/Intent** (`semantic/*.py`): Ghadeer mmBERT, F1 0.94 Persian, lazy-loaded
- **Observability** (`observability.py`): Structured logging with `request_id`, `stage`, `decision`, `latency_ms`

## Project Structure

```
components/guardrails/
├── README.md
├── pyproject.toml
├── .env.example
├── config/
│   ├── config.yml
│   └── rails.co
├── kb/
│   ├── hurtlex_allowlist.json
│   ├── hurtlex_fa_conservative.json
│   └── persian_swear.json
└── src/work_rag_guardrails/
    ├── api.py                 # FastAPI: /health, /ready, /v1/rails/check, /v1/chat/completions
    ├── config.py              # Pydantic settings (LLM_BASE_URL alias)
    ├── models.py              # Pydantic request/response models
    ├── service.py             # Core logic: rail checks, guarded generation
    ├── actions.py             # Deterministic actions (HurtLex, profanity, allowlist)
    ├── observability.py       # Structured logging
    ├── risk/
    │   └── scorer.py          # Risk thresholds
    └── semantic/
        ├── toxicity.py        # Ghadeer mmBERT
        ├── hate.py            # Ghadeer mmBERT
        └── intent.py          # Ghadeer mmBERT
```

## Running Locally

```bash
cd components/guardrails
PYTHONPATH=./src \
GUARDRAILS_HOST=0.0.0.0 GUARDRAILS_PORT=8200 \
UPSTREAM_LLM_BASE_URL=http://127.0.0.1:18000/v1 \
UPSTREAM_LLM_MODEL=unsloth/gemma-4-31B-it-GGUF:UD-Q4_K_XL \
/tmp/guard-venv/bin/python -m uvicorn work_rag_guardrails.api:create_app --factory --host 0.0.0.0 --port 8200
```

## Tests

```bash
cd components/guardrails
PYTHONPATH=./src /tmp/guard-venv/bin/python -m pytest tests/ -v
# test_hurtlex_allowlist.py: 26 tests (15 benign + 11 malicious)
# test_input_rails.py: 6 tests
# test_output_rails.py: 9 tests
```

## Verification

```bash
# Health
curl -s http://127.0.0.1:8200/health | jq .
curl -s http://127.0.0.1:8200/ready | jq .

# Input allowed (was blocked before allowlist)
curl -s http://127.0.0.1:8200/v1/rails/check -H 'Content-Type: application/json' \
  -d '{"stage":"input","text":"درخواست حذف سابقه منفی قدیمی از گزارش اعتباری","request_id":"t"}' | jq .

# Output blocked for true hate
curl -s http://127.0.0.1:8200/v1/rails/check -H 'Content-Type: application/json' \
  -d '{"stage":"output","text":"این فرد حرامزاده است","request_id":"t"}' | jq .
```

## Links

- [Parent README](../README.md)
- [Architecture](../docs/architecture.md#guardrails-pipeline)
- [Models](../docs/models.md#guardrails-models)
- [GUARDRAILS_V2_PLAN](../docs/GUARDRAILS_V2_PLAN.md)
- [MVP Integration Plan](../docs/MVP_INTEGRATION_PLAN.md)