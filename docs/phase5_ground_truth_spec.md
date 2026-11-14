# Phase 5.1 Ground-Truth and Record Specification

This specification defines planned records and verification for the future 15-scenario benchmark. It creates no executable schema or scenario file. Expected labels are authored and verified separately from agent outputs. Phase 3 and Phase 4 results are evidence for comparison, not automatic ground truth.

## Three separate event artifacts

Keep the following artifacts distinct in the frozen benchmark and execution flow:

### A. Agent-facing natural-language notice

This synthetic maritime disruption notice is the primary input to the Disruption Intelligence Agent. It may include operational context, but must not expose hidden structured ground-truth labels, expected impact sets, or expected recovery decisions. Preserve the exact notice text and its version/hash. For SC-014, the notice is intentionally incomplete or ambiguous, such as an arrival restriction without a definite end time or with unclear operational scope.

### B. Agent-generated structured event

The Disruption Intelligence Agent extracts the supported event type, port or service identifier, start/end timestamps, closure operations or service `DEPARTURE_WINDOW` semantics, delay duration when relevant, and missing information/unresolved ambiguities. This is an observed agent output, not ground truth. Only a complete event that passes existing Phase 3 validation may be sent to Phase 3. In SC-014, no valid event may be produced or submitted until clarification supplies the missing essential information; record a clarification request or explicitly unresolved result instead. This milestone defines no extraction, validation, or ingestion implementation.

### C. Hidden reference event/outcome

Author a separate structured reference from the notice design and frozen dataset facts. It records the expected event fields for complete notices and is withheld from evaluated agents. For incomplete notices such as SC-014, explicitly record `valid_event_expected: false`, the unresolved/missing fields, and the required clarification; do not invent a canonical value to complete it. The reference is used only after outputs are preserved to score interpretation and safe handling.

## Structured event payload for Phase 3

For complete cases, the executable event payload passed to Phase 3 must conform to the existing schema version `1.0`; the following is a planning shape, not a replacement schema:

```json
{
  "schema_version": "1.0",
  "scenario_id": "SC-XXX",
  "events": [
    {
      "event_id": "event-local-id",
      "type": "PORT_CLOSURE",
      "target_port_id": "<known dataset port ID>",
      "start_time": "timezone-aware ISO-8601 timestamp",
      "end_time": "timezone-aware ISO-8601 timestamp",
      "affected_operations": ["DEPARTURE"],
      "source_type": "SIMULATED",
      "description": "scenario author description"
    }
  ]
}
```

This payload illustrates a complete structured event, not the agent-facing notice or hidden reference label. Fields are conditional: closures require a port target and may specify operations; service suspension/delay require a service target and departure-window semantics; delay requires nonnegative hours. Use unique event IDs, valid known entity IDs, timezone-bearing timestamps with `start_time < end_time`, and the existing half-open interval rule. Omit inapplicable fields. This is a benchmark fixture format over synthetic modeled records, not a claim that the event was observed in reality.

## Expected ground-truth record

Keep one expected-label record per scenario, with shipment-level labels where applicable. Example planning structure:

The following shows a complete-notice example (`valid_event_expected: true`). For SC-014, set it to `false`, leave `events` empty, and fill `unresolved_fields` and `required_clarification`; no structured event is expected until clarification.

```json
{
  "scenario_id": "SC-XXX",
  "label_version": "1",
  "verification_status": "UNVERIFIED | VERIFIED | AMBIGUOUS | UNVERIFIABLE",
  "agent_notice_ref": "notice artifact ID/hash; notice text is stored separately",
  "hidden_reference_event": {
    "valid_event_expected": true,
    "events": [{"event_id": "...", "type": "...", "target_id": "...",
      "start_time": "...", "end_time": "...", "operations": [], "delay_hours": null}],
    "unresolved_fields": [],
    "required_clarification": []
  },
  "expected_impact": {
    "affected_shipments": [{"shipment_id": "...", "direct_or_indirect": "...",
      "reason_codes": ["..."], "leg_ids": ["..."]}],
    "unaffected_shipments_or_cohort_rule": "..."
  },
  "expected_recovery": [{"shipment_id": "...",
    "independent_feasibility": "FEASIBLE | INFEASIBLE_WITHIN_VERIFIED_SCOPE | UNKNOWN | NOT_APPLICABLE",
    "reference_routes": [],
    "expected_safe_agent_behavior": "...",
    "reason": "...", "required_constraints": []}],
  "expected_missing_information": [],
  "evidence_refs": ["evidence record IDs"],
  "review_notes": "limits, ambiguity, or adjudication"
}
```

Keep independent reference outcomes separate from solver execution statuses. Ground truth describes independently established facts under the frozen modeled assumptions. Record these concepts independently:

- **Independent recovery feasibility:** `FEASIBLE`, `INFEASIBLE_WITHIN_VERIFIED_SCOPE`, `UNKNOWN`, or `NOT_APPLICABLE`. An infeasible label must state the exhaustively checked scope; it is not global mathematical infeasibility beyond that scope.
- **Reference route evidence:** zero or more independently verified feasible alternative routes, with modeled departures, arrivals, costs, and constraint calculations. A route can be independently known feasible even if Phase 4 does not find it.
- **Expected safe agent behavior:** for example, recommend a validated route when supported, report infeasibility only within the verified scope, request operator intervention when essential facts/policy are missing, or report the search/outcome as inconclusive.
- **Observed Phase 4 execution status:** preserve verbatim the status actually returned by the bounded solver (`UNCHANGED`, `NO_REROUTE_REQUIRED`, `RECOVERED`, `NO_FEASIBLE_ROUTE`, `DEADLINE_INFEASIBLE`, `OPERATOR_INTERVENTION_REQUIRED`, or `SEARCH_LIMIT_REACHED`) in the execution record, never as a substitute for independent feasibility.

Thus an independently verified feasible route and an observed `SEARCH_LIMIT_REACHED` can coexist: reference feasibility remains `FEASIBLE`, while execution status remains `SEARCH_LIMIT_REACHED` and safe agent reporting is inconclusive about that solver result. Do not equate `SEARCH_LIMIT_REACHED` with infeasibility, `NO_FEASIBLE_ROUTE` with global mathematical infeasibility, or `OPERATOR_INTERVENTION_REQUIRED` with ordinary search failure. A validator PASS supports feasibility under checked modeled constraints, not globally optimal recovery.

Where there is no affected shipment, document the complete cohort/selection rule checked and the resulting empty impact set. For operator-required labels, record each missing essential operational fact or supported policy. Never invent vessel position, diversion options, or unsupported arrival/transshipment handling policy.

## Agent execution result record

One result record is required for each scenario/run pair, with trace data retained or referenced:

```json
{
  "scenario_id": "SC-XXX",
  "run_id": "SC-XXX-R1",
  "completion_status": "COMPLETED | FAILED | INCOMPLETE",
  "started_at": "timestamp",
  "ended_at": "timestamp",
  "runtime_seconds": null,
  "agent_outputs": [{"role": "provisional role", "input_ref": "...",
    "output": {}, "trace_ref": "..."}],
  "interpreted_events": [],
  "reported_impacts": [],
  "generated_structured_events": [],
  "missing_information_or_ambiguities": [],
  "decisions": [{"shipment_id": "...", "classification": "...",
    "recommended_route": null, "phase4_execution_status": null, "evidence_refs": []}],
  "tool_calls": [{"tool": "...", "arguments_ref": "...", "status": "...",
    "error": null, "duration_seconds": null}],
  "invalid_recommendations": [],
  "token_usage": {"input": null, "output": null, "available": false},
  "approximate_cost": {"amount": null, "currency": null, "basis_ref": null},
  "model_and_environment": {"model": "...", "prompt_version": "...",
    "code_commit": "...", "tool_versions": {}, "dataset_hashes": {}, "policy_hash": "..."},
  "metric_results": {},
  "notes": ""
}
```

Use null/unavailable explicitly rather than estimating missing runtime, token use, or price as zero. Keep credentials and sensitive data out of traces; any redaction should preserve enough evidence to audit tool selection, inputs, outputs, sequence, and claims.

## Verification procedure

1. **Select and pin inputs.** Record the dataset build/manifest and hashes of ports, services, shipments, plans, policy, and relevant code. Inspect the actual frozen records before choosing case targets and timestamps. Validate proposed input against the existing Phase 3 validator during later construction; do not modify semantics to make a case fit.
2. **Author labels before agent runs.** Write the expected event interpretation, impact set/reasons, recovery classifications, acceptable routes, and missing information independently of LLM traces. Keep the expected-label file inaccessible to the evaluated agents.
3. **Check impact independently.** For each candidate affected route, enumerate its planned legs and calculate event overlap against the actual operation/transfer semantics. Service events match departures inside `[start_time,end_time)`; closures apply only to selected operations and the corresponding instants or transfer interval. Recompute delay effect and connection readiness. For SC-013, verify a planned departure exactly equal to `end_time` is excluded and verify no other targeted-service departure lies inside the event interval, preserving the intended no-impact label. For SC-006, verify no planned departure lies inside the suspension interval. Reconcile both positive and negative cases against the full chosen shipment cohort. A small hand-maintained calculation worksheet or independently written reference calculation is suitable; it must not merely copy Phase 3 outputs.
4. **Check recovery independently.** Inspect the directed graph and apply departure recurrence from the configured epoch, transit duration, minimum transfer time, disruption rules, cargo compatibility, individual capacity, max hops, horizon, and deadline. Calculate route arrival and modeled cost by hand or with a separate calculation. Check the route with Phase 4's independent validator as corroboration. Do not treat the current solver's selected route or status as sole ground truth. Record independent feasibility as `FEASIBLE`, `INFEASIBLE_WITHIN_VERIFIED_SCOPE`, `UNKNOWN`, or `NOT_APPLICABLE`; if search limits or missing evidence prevent exhaustive verification, use `UNKNOWN` for reference feasibility. Preserve the actual Phase 4 execution status independently, including `SEARCH_LIMIT_REACHED` where returned. Never infer independent infeasibility from a solver status alone.
5. **Record operational boundaries.** For arrival closures, do not assume where the vessel is or invent carrier-authorized diversions. For transshipment closures, do not assume holding, unloading, transfer, or departure. Where these facts/policies are missing, label intervention and list them. Do not conflate infeasibility with missing information.
6. **Review and freeze.** Check IDs, times, impact counts, route calculations, status mapping, evidence links, and ambiguity with a second pass by the student. Record the reviewer role honestly. No maritime expert is assumed; call results “student-verified against the modeled dataset and stated rules,” not expert-validated. If a qualified reviewer actually participates, record their qualifications and review scope without overstating it.

## Evidence, provenance, and independent outcome record

Each evidence item should have an ID and include, as applicable: source file/record and canonical ID; source file SHA-256; dataset manifest/build; scenario and policy hash; calculation method/version; calculation inputs and intermediate arithmetic; validator output and constraint-by-constraint results; Phase 3/4 version and output hash (clearly marked corroborating system evidence); verification date; author/reviewer and role; status; and notes on limitations. Retain both raw observation and derived calculation. Derived labels must point to their inputs.

An independently verified outcome record should state: what was checked; the expected label and rationale; evidence references; whether Phase 3/4 agreed; any discrepancy and its resolution; whether a feasible route was shown or exhaustively excluded within scope; and residual uncertainty. A tool disagreement prompts investigation and a recorded adjudication, not automatic preference for either tool or label.

## Ambiguous and unverifiable cases

Mark a case `AMBIGUOUS` when multiple interpretations remain consistent with the prompt or modeled evidence; mark `UNVERIFIABLE` when required frozen data or a defensible calculation is unavailable. Record the ambiguity, missing evidence, and affected labels. Do not score unresolved fields as correct/incorrect without a predeclared rule. Replace or exclude a case before freezing if it cannot test its intended capability, preserving a change log and the 15-case distribution. Do not silently turn a search limit into a negative route label or treat absent operational policy as permission to guess.

## Separation of inputs and hidden expected results

Maintain agent-facing natural-language notices, agent-generated structured events, hidden reference events/outcomes, and expected ground-truth labels as distinct artifacts. Evaluated agents receive the notice and ordinary tool access needed for the task; they do not receive the structured reference, label notes, expected impact set, expected recovery decision, or answer-specific filenames. The generated event is an observed agent output. Only a complete, validated event is passed to Phase 3; an incomplete notice such as SC-014 is held for clarification and produces no Phase 3 event call. Keep hidden labels in a separate restricted location or controlled evaluation copy, compare results only after runs are saved, and preserve raw agent outputs before adjudication. The public planning catalog is not an executable input set and contains no canonical identifiers or answer key.

## Freezing the evaluation dataset

Before the final 45-run evaluation, assign a benchmark version and freeze/hash: all 15 validated scenario payloads; scenario descriptions given to agents; expected labels and evidence records; Phase 2 dataset manifest and canonical files; Phase 4 policy; prompts/configuration; code commit and dependency environment; model/provider/version settings available; and this scoring protocol. Record a run manifest mapping each scenario to exactly three distinct run IDs. Do not edit artifacts in place after runs begin. Any substantive change creates a new version, records why it changed, and invalidates comparability with affected runs. Phase 5.1 defines these controls; it does not create or freeze that dataset.
