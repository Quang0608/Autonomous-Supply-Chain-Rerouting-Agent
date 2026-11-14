# Phase 5.1 Evaluation Protocol and Scenario Design

## Purpose and scope

This protocol plans evaluation of the future CrewAI-based Autonomous Supply Chain Reroute Agent. It covers 15 scenarios, each run three times (45 planned end-to-end runs). It evaluates specialized-agent behavior, tool coordination, shipment impact and recovery decisions, operator intervention, and repeatability. This is a focused software-oriented FYP evaluation, not a large comparative research benchmark.

Phase 5.1 defines methods and planned cases only. It does not implement agents, create executable scenarios, verify case feasibility, or run the evaluation. Every catalog entry begins `UNVERIFIED`; actual scenario construction and verification are later work. Phase 3 and Phase 4 remain deterministic tools whose outputs are evidence to inspect, not unquestioned labels.

## Why 15 scenarios

Fifteen cases provide a deliberately bounded set for a one-student project: enough to cover each supported disruption family, isolated and compound conditions, unaffected shipments, and cases that require restraint or an operator. Three repetitions expose variability without implying statistical power. Results should be reported as descriptive case-level findings, not broad claims about maritime operations or all multi-agent systems.

## System facts and evaluation boundary

The current implementation supports `PORT_CLOSURE`, `SERVICE_SUSPENSION`, and `SERVICE_DELAY`. Scenario inputs use schema version `1.0`, a non-empty `scenario_id`, and one or more events with unique `event_id`, timezone-aware ISO timestamps, and a positive-duration `[start_time, end_time)` interval. A closure targets a known `target_port_id` and can specify `ARRIVAL`, `DEPARTURE`, and/or `TRANSSHIPMENT` operations (omitted operations normalize to all three). Suspension and delay target a known `target_service_id` and use `DEPARTURE_WINDOW`; delay also requires nonnegative `delay_hours`. Time is interpreted against a simulated UTC epoch of 2025-01-01, not real sailing schedules.

**Documentation discrepancies found:** the README introduction and “Limitations and next phase” still describe Phase 3 and Phase 4 as future work, although the implementation and dedicated Phase 3/4 reports are present. Also, `docs/phase3_disruption_schema.json` requires `affected_operations` for closures and `semantics` for service events, while `phase3.validate_scenario` defaults omitted closure operations to all operations and omitted service semantics to `DEPARTURE_WINDOW`. For evaluation fixtures, follow the implementation and preserve explicit fields in the frozen cases to avoid ambiguity.

Phase 3 identifies direct/indirect impact and no-recovery outcomes. Phase 4 searches a bounded directed graph with the configured policy (`max_hops=4`, `horizon_days=180`, three candidate departures per service and bounded search limits) and calls an independent route feasibility validator. Its statuses are `UNCHANGED`, `NO_REROUTE_REQUIRED`, `RECOVERED`, `NO_FEASIBLE_ROUTE`, `DEADLINE_INFEASIBLE`, `OPERATOR_INTERVENTION_REQUIRED`, and `SEARCH_LIMIT_REACHED`. `SEARCH_LIMIT_REACHED` is inconclusive about route existence. A validator PASS establishes modeled feasibility against checked constraints, not global optimality or real-world bookability. Recovery models individual shipment capacity, not residual shared bookings.

`OPERATOR_INTERVENTION_REQUIRED` is appropriate where essential operational information or supported policy is absent. The code specifically does not infer vessel position/diversion for a closed arrival or handling policy for affected transshipment; these produce missing-information reasons. Do not invent those facts. A missed fixed connection from a service delay is modeled and can be a recovery starting point. Arrival/departure/transfer semantics and their phase-specific limits must be kept distinct.

## Scenario selection and coverage

The catalog covers exactly:

| Category | Count | Coverage intent |
|---|---:|---|
| Port closures | 3 | Departure blocking with alternate-route opportunity; arrival/transfer closure with unsupported operational state; no-impact closure |
| Service suspensions | 3 | Alternative recovery; no feasible path or deadline limitation; no shipment impact |
| Service delays | 3 | Delay absorbed by schedule slack; delay causing a missed connection; overlapping/compounding downstream effects |
| Compound disruptions | 2 | Interacting supported events, including overlapping events and multi-leg consequences |
| No-impact scenarios | 2 | Valid event outside shipment operations/time window and a disruption affecting no shipment |
| Missing information / operator intervention | 2 | Arrival closure with unknown vessel state; transshipment closure with absent handling policy |
| **Total** | **15** | |

These are coverage labels, not additional event types. Each input will use only the three supported semantics. Cases should be selected from the frozen dataset after inspecting actual routes, times, and modeled network. No canonical IDs, timestamps, impacted shipment counts, or outcome labels are asserted here. If a proposed case cannot be constructed as intended on the frozen dataset, record it as unverified/unavailable and select a justified replacement during the later construction phase; do not silently alter its expected behavior.

## Evaluation areas

### A. Agent-level functionality

The following are provisional roles, not a requirement for five separate CrewAI agents. The final implementation may combine roles if evaluation evidence still covers each capability.

| Provisional role | Expected input | Expected output | Evaluation criteria |
|---|---|---|---|
| Disruption Intelligence Agent | Natural-language incident description and scenario context | Structured event type, target entity, interval, operation scope, assumptions/uncertainties | Correct supported type and fields; valid time window; no unsupported facts; asks for missing essential details or flags ambiguity |
| Shipment Investigation Agent | Structured event and dataset/tool access | Affected shipment set, impact reasons, relevant plan/leg evidence | Correct cohort and reasons against independent labels; uses impact tool appropriately; distinguishes direct and downstream effects |
| Recovery Planning Agent | Impact evidence, shipment constraints, Phase 4 tool interface | Proposed tool request and shipment-level plan/status interpretation | Selects deterministic recovery tool; preserves tool output; does not fabricate routes, feasibility, positions, or policies |
| Recovery Review Agent | Candidate plan, validation checks, constraints | Review disposition and any failed/unsupported checks | Correctly interprets PASS/FAIL/UNSUPPORTED; rejects invalid recommendations; does not equate PASS with optimality |
| Decision and Reporting Agent | Prior tool results, validation, scenario labels | Grounded recommendations, status, rationale, intervention request where needed | Recommendations trace to evidence; classifications correct; states uncertainty/limits; no unsupported maritime claims |

Capture per-role input/output or trace references where the framework permits. Score capability-level criteria even if the architecture merges roles. Natural-language interpretation is assessed against the independently authored structured event labels; exact wording is not required.

### B. End-to-end correctness

For each scenario/run, evaluate:

1. **Event interpretation:** event types, target IDs, times, operation scope, delay amount, and explicit uncertainty match the expected labels.
2. **Impact identification:** reported affected shipment IDs equal the independently reconciled expected set; per-shipment direct/indirect reason and leg are consistent with reference calculations.
3. **Recovery classification:** each relevant shipment is correctly classified (including unchanged, no-reroute, recovered, infeasible, search-limited, or operator-required) under the modeled assumptions.
4. **Plan feasibility:** any recommended route is complete and its constraints are independently checked. A recommendation with a failed or unsupported required check is invalid. Compare the agent's plan with Phase 4's candidate, but independently recalculate route constraints and do not assume the solver's selection is ground truth.
5. **Grounded final decision:** each recommendation or intervention request cites the relevant tool result/evidence. Unsupported claims or a route recommendation where the tool returned no plan count as incorrect.

Useful measures (report numerator and denominator, with per-case results):

- Event field exact-match rate = correctly interpreted required fields / required labeled fields.
- Shipment precision = TP/(TP+FP), recall = TP/(TP+FN), and F1; additionally report exact affected-set match rate across scenarios.
- Recovery decision accuracy = correctly classified labeled shipment decisions / all labeled shipment decisions.
- Valid recommendation rate = recommended plans passing all applicable independent checks / all recommended plans. Also report invalid plan count directly.
- Evidence support rate = final factual claims supported by recorded tool/evidence references / audited factual claims.
- Intervention classification accuracy = correct intervention-required/non-required labels / applicable decisions.

An abstention is correct where the independent label calls for missing information or unsupported policy. Do not reward a confident guess for a case labeled ambiguous.

### C. Reliability and robustness

Run every frozen scenario three times using the same dataset, policy, prompts/configuration, tool versions, and declared model settings. Preserve each raw trace and result separately. Record:

- scenario ID, run number, start/end time and completion state (`COMPLETED`, `FAILED`, or `INCOMPLETE`);
- correctness by metric and decision, errors/exceptions, failed/retried tool calls and invalid recommendations;
- agent execution trace or trace reference, including tool name, sanitized arguments, response, and sequence;
- wall-clock runtime and, when available, per-run input/output token counts and approximate cost with pricing/model source and date;
- LLM/model name and version where available, prompt/config version, software commit, Python/dependency environment, Phase 3/4 versions, policy and dataset hashes;
- consistency of event interpretation, affected shipment set, per-shipment classification, and route choice across the three runs.

Report completion rate, error/tool-failure counts, invalid plans, per-scenario accuracy over runs, and consistency. Define decision consistency as identical normalized decisions on all three runs for a scenario; report route consistency separately because multiple independently verified feasible routes may be acceptable. Also show the range or all three observations for numeric measures. Do not hide failed runs or average away an unsafe recommendation.

Deterministic correctness and LLM reliability are separate: Phase 3/4 regression checks or repeatable outputs establish behavior of deterministic tools under fixed inputs; the agent evaluation measures whether an LLM-driven workflow interprets, calls, and reports those tools reliably. Repeated runs do not make LLM outputs deterministic and three observations do not support population-level reliability claims.

## Independent ground truth

Use a lightweight, auditable reference process suitable for one student without assumed access to domain experts:

1. Freeze the canonical dataset and recovery policy snapshots for scenario design. Select actual targets and event times by inspecting the relevant records; retain IDs only in the later scenario artifacts, not this planning catalog.
2. Write scenario input and expected labels independently before examining agent outputs. Record the expected event fields, affected shipments/reasons, expected recovery classification, feasible route evidence if known, and missing-information handling.
3. Reconcile Phase 3 impact labels against a separate hand-check/reference calculation: enumerate planned legs and compare operation instants or transfer intervals to `[start,end)`; apply departure-window semantics for service events; derive delay propagation and downstream connection conflict from recorded plan times. A small independent spreadsheet/script may assist later, but must not call Phase 3 as its sole label source.
4. For route outcomes, manually inspect directed service edges, frequency departures from the configured epoch, transit times, transfer readiness, closure/suspension/delay interactions, cargo class, individual capacity, horizon, hop bound, and hard deadline. Independently recompute candidate route timing and modeled cost. Use Phase 4 validator output as corroborating evidence, not independent truth. For a “no feasible route” label, exhaustively enumerate the bounded modeled search space or otherwise provide a defensible exhaustive argument under the frozen policy; if search was limited or completeness cannot be shown, label the result inconclusive rather than impossible.
5. Review all labels for internal consistency and preserve evidence and calculation steps. A qualified maritime expert is not guaranteed; do not claim expert validation unless one actually participates. Describe labels as student-verified against the modeled dataset and explicit rules.

## Reproducibility, validity and limitations

The later frozen benchmark should include hashes for scenario inputs, expected labels, canonical dataset files/manifest, recovery policy, prompts, code commit, and environment; fixed simulation epoch/time zone; stable run IDs; saved raw outputs and trace references; and recorded model version/settings. Keep source and derived artifacts read-only during runs. Any change requires a new benchmark version and rerun plan.

Threats include synthetic schedules and gateways, modeled service availability/cost/capacity, a maritime-only graph, no shared capacity reservation, bounded search, selected cases not representing real disruption frequencies, student-authored labels without guaranteed expert review, potential label/tool coupling, stochastic LLM outputs, and a small sample. Phase 4 PASS is feasibility under modeled constraints, not global optimality. `SEARCH_LIMIT_REACHED` is not proof of no route. Results should not be generalized to deployed logistics or real carrier operations.

## Phase 5 acceptance criteria

Phase 5 evaluation can be reported as complete only when:

- exactly 15 executable, schema-valid scenarios have been frozen with the required category distribution, actual canonical IDs/times, and provenance hashes;
- every included case has feasibility status resolved, purpose and expected labels documented, and no planned-only/unverified label presented as verified;
- independent impact and outcome evidence exists for all scored labels, with ambiguity or inconclusive bounded-search cases explicitly handled;
- the three-run protocol is completed for each scenario (45 run records), failures included, with environment, outputs, traces, runtime, and available token/cost data recorded;
- agent-level and end-to-end metrics are calculated with denominators, invalid recommendations and tool errors disclosed, and deterministic tool correctness distinguished from LLM reliability;
- conclusions stay within the modeled software evaluation scope and do not claim expert validation, global optimality, or real-world operational performance without evidence.

These are planned criteria. None is claimed satisfied by Phase 5.1.
