# ADS Live Operating Policy

- Owner: Workbench for development surfaces, Orchestrator for live control-plane decisions.
- Status: production-readiness mode is allowed; bounded production-pilot scoreable canaries are allowed under calibration-debt controls; unattended scoreable live operations remain blocked.

## Allowed Now

- Bounded one-case or cloned scheduler runs using `predquant.ads_production_readiness_handlers:build_stage_handlers`.
- Bounded one-case or two-case scheduler runs using `predquant.ads_production_pilot_handlers:build_stage_handlers` only with `--require-live-readiness --require-scoreable-live --allow-calibration-debt-scoreable-canary --max-cases <= 2`.
- `--allow-non-scoreable` canary runs that require strict manifest handoffs and `--skip-existing-ads-predictions`.
- Live-readiness checks through `check_ads_live_readiness.py` without `--require-scoreable-live`.
- Storage-maintenance dry runs and operator-reviewed maintenance applies.
- Non-authoritative scoring and calibration-debt reports.

## Required Controls

- Pipeline control must be disabled after every bounded run with `default_disable_action=no_new_leases`.
- Active ADS runs and active ADS case leases must be zero before a new bounded run.
- `check_pipeline_health.py` must return `ok=true` before live production-readiness runs.
- Every downstream stage must return persisted artifact manifest refs when `--require-manifest-handoffs` is set.
- Production-readiness runs must produce a forecast decision record but must not write `market_predictions`.
- Production-pilot scoreable canaries must use structured market metadata certification, strict manifest handoffs, `--skip-existing-ads-predictions`, and automatic post-run disable.
- Scoreable live scheduler runs must pass `run_ads_operational_scheduler.py --require-live-readiness --require-scoreable-live`; while CAL-001 is blocked they must also pass the explicit bounded canary allowance.

## Blocked Until Further Evidence

- Scoreable live prediction writes outside the production-pilot bounded canary lane.
- Any unattended live scheduler path that does not require live readiness.
- Any handler factory containing the canary handler surfaces unless explicitly allowed for a canary-only test.
- Continuous calibration-debt production as a scoreable live path until CAL-001 clears.
- Production-pilot batches larger than two cases while calibration debt remains active.

## Live Cutover Gate

Scoreable live operations require all of the following:

- Real specialist adapters for live retrieval, source metadata classification, researcher classification, verification, and SCAE-ready sufficiency reconciliation beyond the structured market metadata pilot lane.
- SCAE final probability fields produced only after SCAE-013 research sufficiency passes.
- CAL-001 calibration-debt clearance, including first-100 trace completeness, scorecards, tail/regime/protected-component diagnostics, and pointer stability.
- A clean cloned DB scheduler run and a clean bounded live run with no active leases or runs left behind.
- Operator approval to remove the non-scoreable production-readiness stance.
