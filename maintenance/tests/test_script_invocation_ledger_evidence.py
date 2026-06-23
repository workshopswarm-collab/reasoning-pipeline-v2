#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

MAINTENANCE_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = MAINTENANCE_ROOT.parent
ORCHESTRATOR_ROOT = WORKSPACE_ROOT / 'orchestrator'
EVIDENCE_DIR = MAINTENANCE_ROOT / 'orchestrator-repo-maintenance' / 'generated' / 'script-invocation-ledger'
B1_BASELINE_PATH = EVIDENCE_DIR / 'script-invocation-ledger-b1-baseline-2026-05-17.json'
B2_PARITY_PATH = EVIDENCE_DIR / 'script-invocation-ledger-b2-check-pipeline-health-parity-2026-05-17.json'
B3_WRAPPER_PATH = EVIDENCE_DIR / 'script-invocation-ledger-b3-wrapper-only-coverage-2026-05-17.json'
B4_SUBPROCESS_PATH = EVIDENCE_DIR / 'script-invocation-ledger-b4-pipeline-automation-status-subprocess-2026-05-17.json'
B5_TRIGGER_PATH = EVIDENCE_DIR / 'script-invocation-ledger-b5-launchd-trigger-hints-2026-05-17.json'
B6_ENTRYPOINT_PATH = EVIDENCE_DIR / 'script-invocation-ledger-b6-watch-pipeline-entrypoint-2026-05-17.json'
SHA256_PATTERN = re.compile(r'^sha256:[0-9a-f]{64}$')


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding='utf-8'))
    assert isinstance(payload, dict), f'{path} did not contain a JSON object'
    return payload


def test_b1_baseline_artifact_declares_maintenance_owned_evidence_scope() -> None:
    payload = load_json(B1_BASELINE_PATH)

    assert payload['schema_version'] == 'openclaw-script-invocation-ledger-baseline/v1'
    assert payload['phase'] == 'B1'
    assert payload['evidence_owner'] == 'maintenance/orchestrator-repo-maintenance'
    assert payload['evidence_path'] == B1_BASELINE_PATH.relative_to(WORKSPACE_ROOT).as_posix()
    assert payload['instrumentation_changes_in_this_slice'] is False
    scope = payload['baseline_scope']
    assert scope['production_entrypoints_edited'] is False
    assert scope['production_state_mutation_allowed'] is False
    assert scope['first_direct_instrumentation_target'] == 'scripts/check_pipeline_health.py'


def test_b1_candidate_targets_have_non_mutating_commands_and_expectations() -> None:
    payload = load_json(B1_BASELINE_PATH)
    targets = payload['candidate_targets']
    assert len(targets) >= 4

    for target in targets:
        script = target['script']
        assert (ORCHESTRATOR_ROOT / script).exists(), script
        assert SHA256_PATTERN.match(target['pre_instrumentation_sha256']), target
        assert isinstance(target['pre_instrumentation_size_bytes'], int)
        assert target['pre_instrumentation_size_bytes'] > 0
        assert target['baseline_commands']
        for command in target['baseline_commands']:
            assert command['safe_smoke_command'] is True, command['id']
            assert command['mutates_production_state'] is False, command['id']
            assert command['expected_exit_code'] == 0, command['id']
            assert 'stdout_expectation' in command, command['id']
            assert command['stderr_expectation']['mode'] == 'empty', command['id']


def test_b1_next_slice_points_to_healthcheck_b2_parity_commands() -> None:
    payload = load_json(B1_BASELINE_PATH)
    next_slice = payload['next_slice']
    assert next_slice['slice'] == 'B2'
    assert next_slice['target'] == 'scripts/check_pipeline_health.py'
    assert sorted(next_slice['required_pre_post_parity_commands']) == [
        'check-pipeline-health-control-disabled-smoke',
        'check-pipeline-health-help',
    ]


def test_b2_parity_artifact_records_passed_non_mutating_checks() -> None:
    payload = load_json(B2_PARITY_PATH)

    assert payload['schema_version'] == 'openclaw-script-invocation-ledger-parity/v1'
    assert payload['phase'] == 'B2'
    assert payload['evidence_owner'] == 'maintenance/orchestrator-repo-maintenance'
    assert payload['evidence_path'] == B2_PARITY_PATH.relative_to(WORKSPACE_ROOT).as_posix()
    assert payload['instrumented_script'] == 'scripts/check_pipeline_health.py'
    assert payload['baseline_reference']['artifact'] == B1_BASELINE_PATH.relative_to(WORKSPACE_ROOT).as_posix()
    assert payload['instrumentation_summary']['production_state_mutation_allowed'] is False
    commands = {command['id']: command for command in payload['parity_commands']}
    assert set(commands) == {'check-pipeline-health-help', 'check-pipeline-health-control-disabled-smoke'}
    for command in commands.values():
        assert command['parity_result'] == 'pass', command['id']
        assert command['safe_smoke_command'] is True, command['id']
        assert command['mutates_production_state'] is False, command['id']
        assert command['observed_exit_code'] == command['baseline_expected_exit_code'], command['id']
        assert command['observed_stderr_bytes'] == 0, command['id']
        assert command['ledger_result']['event_sequence'] == ['start', 'finish'], command['id']
        assert command['ledger_result']['finish_exit_code'] == 0, command['id']


def test_b3_wrapper_artifact_records_manual_deprecated_coverage_without_direct_edits() -> None:
    payload = load_json(B3_WRAPPER_PATH)

    assert payload['schema_version'] == 'openclaw-script-invocation-ledger-wrapper-coverage/v1'
    assert payload['phase'] == 'B3'
    assert payload['evidence_owner'] == 'maintenance/orchestrator-repo-maintenance'
    assert payload['evidence_path'] == B3_WRAPPER_PATH.relative_to(WORKSPACE_ROOT).as_posix()
    assert payload['instrumentation_changes_in_this_slice'] is False
    assert payload['production_entrypoints_edited'] == []
    assert payload['production_state_mutation_allowed'] is False
    cross_reference = payload['cross_reference']
    assert cross_reference['b3_artifact_observed_before_this_slice'] is False
    assert cross_reference['run_logged_exists'] is True
    assert cross_reference['no_new_direct_instrumentation'] is True
    assert sorted(cross_reference['prior_completed_slices_observed']) == ['B1', 'B2']


def test_b3_wrapper_commands_are_safe_and_emit_child_ledger_rows() -> None:
    payload = load_json(B3_WRAPPER_PATH)
    commands = payload['wrapper_coverage_commands']
    assert {command['classification_from_committed_inventory']['classification'] for command in commands} >= {
        'deprecated_candidate',
        'manual_repair',
    }
    assert len(commands) >= 3

    for command in commands:
        script = command['script']
        assert (WORKSPACE_ROOT / script).exists() or (ORCHESTRATOR_ROOT / script).exists(), script
        assert SHA256_PATTERN.match(command['sha256']), command
        assert command['safe_smoke_command'] is True, command['id']
        assert command['mutates_production_state'] is False, command['id']
        assert command['production_writes'] == [], command['id']
        assert command['observed_exit_code'] == 0, command['id']
        assert command['observed_stdout_bytes'] > 0, command['id']
        assert command['observed_stderr_bytes'] == 0, command['id']
        ledger = command['ledger_result']
        assert ledger['event_sequence'] == ['start', 'finish'], command['id']
        assert ledger['row_count_for_script'] == 2, command['id']
        assert ledger['start_parent_script'] == 'scripts/run_logged.py', command['id']
        assert ledger['start_trigger'] == 'manual-wrapper-b3', command['id']
        assert ledger['start_trigger_source'] == 'argument', command['id']
        assert ledger['start_subprocess'] is True, command['id']
        assert ledger['finish_status'] == 'completed', command['id']
        assert ledger['finish_exit_code'] == 0, command['id']
        assert ledger['finish_subprocess'] is True, command['id']


def test_b4_subprocess_artifact_records_status_only_instrumentation() -> None:
    payload = load_json(B4_SUBPROCESS_PATH)

    assert payload['schema_version'] == 'openclaw-script-invocation-ledger-subprocess-instrumentation/v1'
    assert payload['phase'] == 'B4'
    assert payload['evidence_owner'] == 'maintenance/orchestrator-repo-maintenance'
    assert payload['evidence_path'] == B4_SUBPROCESS_PATH.relative_to(WORKSPACE_ROOT).as_posix()
    assert payload['instrumented_script'] == 'scripts/pipeline_automation_actions.py'
    summary = payload['instrumentation_summary']
    assert summary['scope'] == 'status-only process liveness check'
    assert summary['function'] == 'process_running(pid)'
    assert summary['production_state_mutation_allowed'] is False
    assert summary['direct_live_dispatch_paths_instrumented'] is False
    cross_reference = payload['cross_reference']
    assert cross_reference['b4_artifact_observed_before_this_slice'] is False
    assert sorted(cross_reference['prior_completed_slices_observed']) == ['B1', 'B2', 'B3']


def test_b4_subprocess_smoke_preserved_result_and_logged_ps_child() -> None:
    payload = load_json(B4_SUBPROCESS_PATH)
    smoke = payload['smoke_command']
    assert smoke['safe_smoke_command'] is True
    assert smoke['mutates_production_state'] is False
    assert smoke['observed_result'] is True
    ledger = smoke['ledger_result']
    assert ledger['event_sequence'] == ['start', 'finish']
    assert ledger['row_count'] == 2
    assert ledger['script'] == 'ps'
    assert ledger['parent_script'] == 'scripts/pipeline_automation_actions.py'
    assert ledger['trigger'] == 'subprocess/status'
    assert ledger['finish_status'] == 'completed'
    assert ledger['finish_exit_code'] == 0
    assert ledger['subprocess'] is True


def test_b5_scheduler_trigger_artifact_records_launchd_hint_only() -> None:
    payload = load_json(B5_TRIGGER_PATH)

    assert payload['schema_version'] == 'openclaw-script-invocation-ledger-scheduler-trigger-hints/v1'
    assert payload['phase'] == 'B5'
    assert payload['evidence_owner'] == 'maintenance/orchestrator-repo-maintenance'
    assert payload['evidence_path'] == B5_TRIGGER_PATH.relative_to(WORKSPACE_ROOT).as_posix()
    assert payload['production_state_mutation_allowed'] is False
    assert payload['trigger_hint'] == {'env_key': 'OPENCLAW_SCRIPT_TRIGGER', 'env_value': 'launchd'}
    assert payload['behavior_contract']['program_arguments_changed'] is False
    assert payload['behavior_contract']['working_directory_changed'] is False
    assert payload['behavior_contract']['schedule_cadence_changed'] is False
    cross_reference = payload['cross_reference']
    assert cross_reference['b5_artifact_observed_before_this_slice'] is False
    assert sorted(cross_reference['prior_completed_slices_observed']) == ['B1', 'B2', 'B3', 'B4']


def test_b5_scheduler_trigger_checks_cover_all_launchd_surfaces() -> None:
    payload = load_json(B5_TRIGGER_PATH)
    rendered = payload['rendered_payload_checks']
    static = payload['checked_in_plist_checks']
    assert len(rendered) == 5
    assert len(static) == 5
    for check in [*rendered, *static]:
        assert check['trigger'] == 'launchd', check
        assert check['path_preserved'] is True, check
        assert check['pythonunbuffered_preserved'] is True, check
        assert check['label'].startswith('ai.openclaw.orchestrator.'), check


def test_b6_entrypoint_artifact_records_watchdog_instrumentation() -> None:
    payload = load_json(B6_ENTRYPOINT_PATH)

    assert payload['schema_version'] == 'openclaw-script-invocation-ledger-entrypoint-instrumentation/v1'
    assert payload['phase'] == 'B6'
    assert payload['evidence_owner'] == 'maintenance/orchestrator-repo-maintenance'
    assert payload['evidence_path'] == B6_ENTRYPOINT_PATH.relative_to(WORKSPACE_ROOT).as_posix()
    assert payload['instrumented_script'] == 'scripts/watch_pipeline.py'
    summary = payload['instrumentation_summary']
    assert summary['production_entrypoints_edited'] == ['scripts/watch_pipeline.py']
    assert summary['production_state_mutation_allowed'] is False
    assert 'logged_main' in summary['wrapper']
    cross_reference = payload['cross_reference']
    assert cross_reference['b6_artifact_observed_before_this_slice'] is False
    assert sorted(cross_reference['prior_completed_slices_observed']) == ['B1', 'B2', 'B3', 'B4', 'B5']


def test_b6_entrypoint_parity_preserved_help_and_logged_rows() -> None:
    payload = load_json(B6_ENTRYPOINT_PATH)
    command = payload['parity_command']
    assert command['id'] == 'watch-pipeline-help'
    assert command['safe_smoke_command'] is True
    assert command['mutates_production_state'] is False
    assert command['baseline_expected_exit_code'] == command['observed_exit_code'] == 0
    assert command['baseline_stdout_bytes'] == command['observed_stdout_bytes']
    assert command['observed_stderr_bytes'] == 0
    assert command['parity_result'] == 'pass'
    ledger = command['ledger_result']
    assert ledger['event_sequence'] == ['start', 'finish']
    assert ledger['row_count'] == 2
    assert ledger['script'] == 'scripts/watch_pipeline.py'
    assert ledger['finish_status'] == 'system_exit'
    assert ledger['finish_exit_code'] == 0


def main() -> int:
    tests = [
        test_b1_baseline_artifact_declares_maintenance_owned_evidence_scope,
        test_b1_candidate_targets_have_non_mutating_commands_and_expectations,
        test_b1_next_slice_points_to_healthcheck_b2_parity_commands,
        test_b2_parity_artifact_records_passed_non_mutating_checks,
        test_b3_wrapper_artifact_records_manual_deprecated_coverage_without_direct_edits,
        test_b3_wrapper_commands_are_safe_and_emit_child_ledger_rows,
        test_b4_subprocess_artifact_records_status_only_instrumentation,
        test_b4_subprocess_smoke_preserved_result_and_logged_ps_child,
        test_b5_scheduler_trigger_artifact_records_launchd_hint_only,
        test_b5_scheduler_trigger_checks_cover_all_launchd_surfaces,
        test_b6_entrypoint_artifact_records_watchdog_instrumentation,
        test_b6_entrypoint_parity_preserved_help_and_logged_rows,
    ]
    failures: list[tuple[str, BaseException]] = []
    for test in tests:
        try:
            test()
            print(f'OK {test.__name__}')
        except Exception as exc:  # noqa: BLE001
            failures.append((test.__name__, exc))
            print(f'FAIL {test.__name__}: {type(exc).__name__}: {exc}')
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
