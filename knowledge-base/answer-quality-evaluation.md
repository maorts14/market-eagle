# Answer-quality evaluation handoff

Status: **human-labeled release gate pending**. The synthetic core suite checks
request validation, calculations, evidence, and presentation contracts. The
cases in `backend/market_eagle/agent/evaluation-v1.json` are programmatic
scenarios and rubric prompts, not human labels or a measured quality baseline.
No broader answer-quality threshold has been chosen or passed.

Use UTF-8 JSON Lines for both inputs and reviews, with one object per line.
For each live or replayed model answer, save one input record with these fields:

| Field | Content |
| --- | --- |
| `case_id`, `dataset_version`, `run_id` | Stable scenario, reviewed dataset version, and evaluation run. |
| `model_id`, `metric_version` | Exact model and analytical definitions used for the answer. |
| `question`, `conversation_context` | User question and only the selected conversation's relevant prior turns. |
| `trusted_result`, `agent_explanation` | Structured calculation/evidence shown by the app and the model-written prose, kept separate. |
| `expected_facts`, `forbidden_claims`, `rubric` | Reviewed case expectations and criteria for grounding, completeness, clarity, and conversation use. |
| `trace_ref` | Reference to the bounded Temporal/tool trace for diagnosis. |

Save each independent human review as a separate output record keyed by
`case_id` and `run_id`. Record `reviewer_id`, `reviewed_at`, and one entry per
applicable criterion with `verdict` (`pass`, `fail`, or `not_applicable`),
`reason`, and the supporting answer excerpt or trusted-result field. Record
`critical_failure` and its reason when a factual claim, coverage statement,
or runtime boundary is wrong. Preserve disagreements between reviewers;
resolve them with a documented adjudication record rather than silently
averaging verdicts. Do not store model credentials in either record.

Build a representative labeled set with valid alternative phrasings and
plausible but unsupported answers. Compare any separate evaluator model's
criterion-by-criterion verdicts with those human labels, inspect
disagreements, and choose the broader release threshold from measured results.
Core factual and boundary failures remain release failures under the
[agent harness contract](agent-harness-contract.md). The human-labeled
answer-quality gate remains open until the labels, calibration, threshold,
and a release run exist. Any operator override must record the failed or
unrun checks, reason, and operator as specified in that contract.
