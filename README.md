# Work RAG Guardrails

NeMo Guardrails boundary for the Work Credit RAG platform.

> Status: repository initialized for submodule integration. The runtime described below is the MVP contract to implement; it is not implemented yet.

## Responsibility

This component owns policy enforcement around the self-hosted Gemma generation service. It does not own retrieval, conversation orchestration, the frontend, or model serving.

For the MVP it will provide:

- deterministic input checks before retrieval and generation;
- a NeMo Guardrails configuration with a small, auditable Colang policy set;
- an OpenAI-compatible chat gateway that calls the Gemma manager in `Work_RAG-Server-Setup`;
- output checks before the response returns to the orchestrator;
- structured decisions and stable refusal responses;
- health and readiness endpoints.

## MVP API contract

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | Process health |
| `GET` | `/ready` | NeMo configuration and upstream Gemma readiness |
| `POST` | `/v1/rails/check` | Run a named input or output policy stage |
| `POST` | `/v1/chat/completions` | OpenAI-compatible guarded Gemma generation |

The guarded generation endpoint will use:

```dotenv
GUARDRAILS_PORT=8200
UPSTREAM_LLM_BASE_URL=http://127.0.0.1:9000/v1
UPSTREAM_LLM_MODEL=gemma-4-31b
UPSTREAM_LLM_API_KEY=sk-local-dev
```

Only Guardrails should call the Gemma manager in the MVP request path. The LangGraph orchestrator calls this guarded gateway.

## Planned structure

```text
.
├── README.md
├── pyproject.toml
├── .env.example
├── config/
│   ├── config.yml
│   └── rails.co
├── src/work_rag_guardrails/
│   ├── api.py
│   ├── config.py
│   ├── models.py
│   └── service.py
└── tests/
    ├── test_input_rails.py
    ├── test_output_rails.py
    └── test_upstream_gemma.py
```

## MVP safety scope

Start deliberately small and measurable:

1. reject empty or oversized input;
2. reject a versioned set of prompt-injection/jailbreak test cases;
3. prevent system/developer prompt disclosure;
4. enforce a generic refusal message without echoing blocked content;
5. reject outputs that expose configured secrets or internal prompt markers;
6. fail closed for policy-engine errors and fail explicitly for upstream-model errors.

Domain-specific credit-policy, PII, compliance, and authorization rails should be added only after owners and expected behavior are defined in tests.

See the parent repository's `docs/MVP_INTEGRATION_PLAN.md` for the cross-component implementation sequence and acceptance criteria.
