# Guardrails KB — Persian sources

Embedded sources for NeMo input/output rails. All `ensure_ascii=false` JSON/TSV, loaded by `actions.py`.

| File | Source | Count | Use |
|---|---|---|---|
| `persian_swear.json` | `Persian-AI/Persian-Swear-Words` `data.json` (master) | 322 | output profanity `check_profanity_fa` |
| `hurtlex_fa.json` / `hurtlex_FA.tsv` | `valeriobasile/hurtlex` `lexica/FA/1.2/hurtlex_FA.tsv` | 2464 | hate/insult `check_hurtlex` (17 categories) |
| `hurtlex_FA.tsv` | original TSV `lemma, category, level` | 3417 lines | reference |
| `persian_swear_raw.json` | raw dump | 322 | backup |
| `prompt_injection_fa.json` | curated from `NOMARJ/sigil` 50+ patterns + `Necent/llm-jailbreak-prompt-injection-dataset` + `TrustAIRLab/in-the-wild-jailbreak-prompts` + `fevziegeyurtsevenler/multilingual-prompt-injection` translated to Persian | 26 patterns | input `check_prompt_injection_fa` |
| `out_of_scope.json` | domain-specific for ICS credit scoring | 20 allowed + 4 blocked categories | input `check_out_of_scope` |

Hate datasets referenced (not vendored, download via HF for classifier training):
- `davardoust/PHICAD` 300k IG, `KamyarDarvishi/Pars-OFF` 10k, `Zahra-D/Phate` 7k, `amirivojdan/naseza` 5.7k, `Pars-HaO` 8k, `OPSD` 22k. Use to train `parsoff-bert` classifier called from `actions.py` if `transformers` available.

All words normalized with `parsitext` pipeline (`\u200c->space`, `ك->ک`, `ي->ی`) before matching.
