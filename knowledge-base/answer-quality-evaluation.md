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
| `model_id`, `metric_version` | Operator-attested model ID and the stored analytical definition version, when a calculation exists. The store does not record the model ID per turn. |
| `question`, `conversation_context` | User question and only the selected conversation's relevant prior turns. |
| `trusted_result`, `model_decision`, `agent_explanation`, `status` | Structured calculation/evidence, model decision and prose, and terminal turn status, kept separate. |
| `expected_facts`, `forbidden_claims`, `rubric` | Reviewed case expectations and criteria for grounding, completeness, clarity, and conversation use. |
| `trace_ref`, `trace_stages` | Route reference and stage/timestamp list; raw trace details are omitted from the export. |

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

## Operator runbook

1. Run the existing cases with a known model and record each terminal turn ID.
   A synthetic fixed-model run checks the export format but does not supply a
   live answer-quality baseline. Add and review new cases in
   [`evaluation-v1.json`](../backend/market_eagle/agent/evaluation-v1.json)
   before assigning real questions that differ from its exact case text.
2. Create a manifest under ignored `local-data/evaluation/` with a unique run
   ID, the exact model ID, and explicit case-to-turn assignments. The operator
   must verify the model ID from the run configuration because turns do not
   store it:

   ```json
   {
     "run_id": "review-run-001",
     "model_id": "nvidia/nemotron-3-super-120b-a12b:free",
     "records": [
       {"case_id": "gain-dollar-frequency-previous-month", "turn_id": "TURN_ID"}
     ]
   }
   ```

3. Export one UTF-8 JSON Lines input file. The command reads only the assigned
   turns, up to eight prior turns from each selected conversation, their trusted
   evidence, and trace stage/times. It omits raw trace details and rejects
   obvious credential fields or values. It refuses a question mismatch, active
   turn, duplicate case, or existing output file. Review the file for private
   content before sharing it with reviewers.

   ```text
   python dev.py agent-evaluation export --manifest local-data/evaluation/manifest.json --output local-data/evaluation/inputs.jsonl
   python dev.py agent-evaluation prepare-reviews --inputs local-data/evaluation/inputs.jsonl --output local-data/evaluation/blank-reviews.jsonl
   ```

4. Give independent reviewers the input file and separate copies of the blank
   review file. For every applicable criterion, each reviewer enters `pass`,
   `fail`, or `not_applicable`, a reason, and a supporting answer excerpt or
   trusted-result field. They also fill `reviewer_id`, an offset-aware
   `reviewed_at`, and `critical_failure` plus a reason when true. Keep each
   completed review as one JSON object per line. Preserve conflicting reviews
   for adjudication.
5. Validate the completed records against the exported cases:

   ```text
   python dev.py agent-evaluation validate-reviews --inputs local-data/evaluation/inputs.jsonl --reviews local-data/evaluation/reviews.jsonl
   ```

   Validation checks shape, evidence, reviewer uniqueness, and coverage. It
   does not score answers or declare a release pass. Human labels and later
   calibration must establish a threshold before the broader gate can run.
