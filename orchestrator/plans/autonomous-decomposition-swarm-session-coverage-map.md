# Autonomous Decomposition-Swarm Session Coverage Map

This file verifies that the individual session plans cover every row in `plans/autonomous-decomposition-swarm-feature-inventory.md` and `plans/autonomous-decomposition-swarm-feature-inventory.yaml`.

## Shared Coordination Model

- The master plan defines architecture and wave sequencing.
- The shared Markdown inventory is the human-readable status board.
- The machine-readable inventory is the executable dependency gate source.
- The script placement map defines the exact workspace and file path for every planned runtime script.
- `python3 plans/check_dependency_gates.py` blocks runtime integration, calibration-debt clearance, and autonomous optimization maturity until upstream rows are ready or explicitly waived. Use `--report-only` only for readiness summaries where `BLOCKED` output is expected.
- The live-cutover blocker matrix, schema-name map, and golden fixture matrix are shared coordination artifacts maintained by Session 1.
- Session plans are worker instructions and local checklists.
- A session directly updates only rows it owns.
- Cross-session changes are proposed in the inventory or handed to Session 1 for reconciliation.
- Fixture-mode work can proceed before dependencies are complete.
- Runtime integration cannot proceed unless upstream dependencies are `done`, `ready_for_integration`, or explicitly waived.

## Coverage by Session

| Session plan | Covered feature IDs |
| --- | --- |
| `autonomous-decomposition-swarm-session-01-foundation-contracts.md` | `FND-001`, `FND-002`, `FND-003`, `FND-004`, `FND-005`, `FND-006`, `FND-007`, `AUTO-001`, `AUTO-002`, `AUTO-003`, `AUTO-004`, `AUTO-005`, `AUTO-006` |
| `autonomous-decomposition-swarm-session-02-evidence-policy-amrg.md` | `CASE-001`, `CASE-002`, `CTX-001`, `CTX-002`, `CTX-003`, `POL-001`, `POL-002`, `POL-003`, `MODEL-001`, `AMRG-001`, `AMRG-002`, `AMRG-003`, `AMRG-004`, `AMRG-005`, `AMRG-006`, `AMRG-007`, `AMRG-008`, `AMRG-009` |
| `autonomous-decomposition-swarm-session-03-decomposer-retrieval.md` | `QDT-001`, `QDT-002`, `QDT-003`, `QDT-004`, `QDT-005`, `MODEL-002`, `RET-001`, `RET-002`, `RET-003`, `RET-004`, `RET-005`, `RET-006`, `RET-007`, `RET-010`, `RET-011`, `RET-009`, `RET-008` |
| `autonomous-decomposition-swarm-session-04-researcher-verification.md` | `CLS-001`, `CLS-006`, `CLS-008`, `CLS-002`, `CLS-003`, `CLS-004`, `CLS-005`, `CLS-007`, `MODEL-003`, `VER-001`, `VER-002`, `VER-003`, `VER-004` |
| `autonomous-decomposition-swarm-session-05-scae-decision-evaluator.md` | `SCAE-001`, `SCAE-002`, `SCAE-003`, `SCAE-004`, `SCAE-005`, `SCAE-006`, `SCAE-007`, `SCAE-008`, `SCAE-009`, `SCAE-010`, `SCAE-011`, `SCAE-012`, `SCAE-013`, `SYN-001`, `DEC-001`, `PERSIST-001`, `PERSIST-002`, `TRACE-001`, `MODEL-004`, `REPLAY-001`, `SCORE-001`, `CAL-001` |
| `autonomous-decomposition-swarm-session-06-evaluator-tuning.md` | `TRACE-002`, `CAL-002`, `CAL-003`, `CAL-004`, `CAL-005` |

## Coverage by Migration Group

| Migration group | Owner session | Covered by plan | Runtime gate |
| --- | --- | --- | --- |
| `MIG-001` foundation/artifact manifest | Session 1 | `autonomous-decomposition-swarm-session-01-foundation-contracts.md` | Required before any runtime artifact write. |
| `MIG-002` stage/status/execution/error records | Session 1 | `autonomous-decomposition-swarm-session-01-foundation-contracts.md` | Required before runtime integration; includes uniform stage execution events and safe log refs for live debugging. |
| `MIG-013` pipeline automation records | Session 1 | `autonomous-decomposition-swarm-session-01-foundation-contracts.md` | Required before continuous runner runtime integration. |
| `MIG-012` existing intake/case contract records | Session 2 | `autonomous-decomposition-swarm-session-02-evidence-policy-amrg.md` | Required before evidence packet runtime integration. |
| `MIG-003` decomposition/QDT records | Session 3 | `autonomous-decomposition-swarm-session-03-decomposer-retrieval.md` | Required before decomposition runtime integration. |
| `MIG-004` retrieval/evidence records | Session 3 | `autonomous-decomposition-swarm-session-03-decomposer-retrieval.md` | Required before retrieval runtime integration. |
| `MIG-005` AMRG records | Session 2 | `autonomous-decomposition-swarm-session-02-evidence-policy-amrg.md` | Required before AMRG runtime integration; local-vector unavailability is a recorded candidate-source diagnostic, not a pipeline blocker. |
| `MIG-006` classification/verification records | Session 4 | `autonomous-decomposition-swarm-session-04-researcher-verification.md` | Required before researcher/verification runtime integration. |
| `MIG-007` SCAE ledger records | Session 5 | `autonomous-decomposition-swarm-session-05-scae-decision-evaluator.md` | Required before SCAE runtime integration. |
| `MIG-008` forecast/decision records | Session 5 | `autonomous-decomposition-swarm-session-05-scae-decision-evaluator.md` | Required before decision runtime integration. |
| `MIG-009` training trace/replay records | Session 5 primary; Session 6 contributor for `TRACE-002` | `autonomous-decomposition-swarm-session-05-scae-decision-evaluator.md`, `autonomous-decomposition-swarm-session-06-evaluator-tuning.md` | Required before v2 live cutover replay cohort begins; full trace materialization is maturity-only. |
| `MIG-010` outcome/scoring records | Session 5 | `autonomous-decomposition-swarm-session-05-scae-decision-evaluator.md` | Required before calibration debt clearance. |
| `MIG-011` calibration/tuning records | Session 6 | `autonomous-decomposition-swarm-session-06-evaluator-tuning.md` | Required before autonomous optimization maturity. |

## Cross-Session Dependency Checkpoints

| Checkpoint | Required upstream rows | Downstream rows unblocked |
| --- | --- | --- |
| Foundation contract freeze | `FND-001`, `FND-002`, `FND-003`, `FND-004`, `MIG-001`, `MIG-002` | All fixture-mode work; runtime integration for Session 2 contracts |
| Runtime script placement freeze | script placement map reviewed, `FIX-039` defined | Implementation sessions may create runtime scripts only at the exact paths listed for Orchestrator, Decomposer, Researcher Swarm, or SCAE |
| Continuous automation runner ready | `AUTO-001`, `AUTO-002`, `AUTO-003`, `AUTO-004`, `AUTO-006`, `MIG-013` | Orchestrator can run end-to-end cases repeatedly only while enabled, and can stop/drain without duplicate leases or forecasts |
| Existing intake case contract ready | `CASE-001`, `CASE-002`, `MIG-012` | `CTX-001`, `QDT-001`, `PERSIST-002`, replay/scoring provenance |
| Evidence, policy, and model context ready | `CTX-001`, `POL-003`, `MODEL-001`, `AMRG-002` or waiver | `QDT-001`, `MODEL-002`, `QDT-002`, `RET-001`, `CLS-001`, `MODEL-003` |
| AMRG vector candidate source ready | `AMRG-009` | Optional vector-neighbor candidates for AMRG; unready/unavailable state must not block `AMRG-002` waiver/artifact or `QDT-001` |
| AMRG typing ready | `AMRG-003` | `QDT-004`, later `AMRG-008` |
| AMRG persistence ready | `MIG-005`, `AMRG-005` | AMRG runtime integration and downstream AMRG tuning diagnostics |
| Decomposition and retrieval ready | `QDT-002`, `RET-001`, `RET-004`, `MIG-003`, `MIG-004` | `CLS-001`, `CLS-002`, `CLS-003` |
| Research sufficiency ready | `QDT-005`, `RET-009`, `RET-008`, `CLS-006`, `CLS-008`, `CLS-005`, `CLS-007`, `VER-004`, `MIG-004`, `MIG-006` | SCAE live-valid evidence intake |
| Verification ready | `VER-001`, `VER-002`, `VER-003`, `VER-004`, `MIG-006` | `SCAE-003`, `SCAE-004`, `SCAE-005`, `SCAE-013` |
| SCAE ledger ready | `SCAE-012`, `MIG-007` | `SYN-001`, `DEC-001`, `PERSIST-001`, `TRACE-001`, `MODEL-004` |
| Forecast/decision persistence ready | `MIG-008`, `PERSIST-001`, `PERSIST-002`, `CASE-002` | Decision runtime integration and scoreable prediction benchmark rows |
| Replay and scoring ready | `MIG-009`, `MIG-010`, `REPLAY-001`, `SCORE-001`, `CAL-001` | Calibration debt clearance work |
| Full trace materialization ready | `TRACE-002`, `MIG-009` contribution | Calibration candidate generation and trace-based diagnostics |
| Calibration lane storage ready | `MIG-011`, `CAL-002` | Autonomous optimization maturity work |
| Live-cutover fixture ready | `FND-*`, cutover `CTX/POL/AMRG/QDT/RET/CLS/VER/SCAE/SYN/DEC/PERSIST/TRACE-001` rows | Non-executing canary and direct production run under `calibration_debt_mode` |
| Model lane provenance ready | `MODEL-001`, `MODEL-002`, `MODEL-003`, `MODEL-004` | Replayable decomposer/researcher model-call traceability |

## Coverage Audit Checklist

- [x] Every inventory feature ID appears in exactly one session plan.
- [x] Every migration group `MIG-001` to `MIG-013` appears in exactly one primary owner session plan; `MIG-009` records the Session 6 `TRACE-002` contribution explicitly.
- [x] Every session plan references the master plan and shared inventory.
- [x] Every session plan references the machine-readable inventory and dependency gate when it owns runtime-gated work.
- [x] Every session plan includes ownership rules.
- [x] Every session plan includes dependency gates.
- [x] Every session plan includes phase-by-phase implementation instructions.
- [x] Every phase includes pseudocode.
- [x] Every phase includes a testing suite.
- [x] Every phase includes a completion checklist.
- [x] Maturity-only work is separated from v2 live-cutover work.
- [x] The live forecast authority boundary remains SCAE-only.
- [x] Session 6 maturity records cannot write production forecasts or base policy files.
