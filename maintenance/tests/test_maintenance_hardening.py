#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lib.maintenance_run import RunEnvelope, StateParseError, load_json_with_context, make_run_id, preflight_path_exists
from lib.maintenance_objective_status import build_objective_rollup, objective_status_from_wrapper
import maintenance_self_check

RUN_MAINTENANCE_PATH = ROOT / 'orchestrator-repo-maintenance' / 'run_maintenance.py'
spec = importlib.util.spec_from_file_location('run_maintenance_for_tests', RUN_MAINTENANCE_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError(f'could not import {RUN_MAINTENANCE_PATH}')
run_maintenance = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = run_maintenance
spec.loader.exec_module(run_maintenance)

RUN_SCHEDULED_MAINTENANCE_PATH = ROOT / 'orchestrator-repo-maintenance' / 'run_scheduled_maintenance.py'
scheduled_spec = importlib.util.spec_from_file_location('run_scheduled_maintenance_for_tests', RUN_SCHEDULED_MAINTENANCE_PATH)
if scheduled_spec is None or scheduled_spec.loader is None:
    raise RuntimeError(f'could not import {RUN_SCHEDULED_MAINTENANCE_PATH}')
run_scheduled_maintenance = importlib.util.module_from_spec(scheduled_spec)
sys.modules[scheduled_spec.name] = run_scheduled_maintenance
scheduled_spec.loader.exec_module(run_scheduled_maintenance)


def test_preflight_missing_path() -> None:
    missing = Path('/tmp/openclaw-maintenance-test-missing-never')
    try:
        preflight_path_exists(missing, 'missing fixture')
    except Exception as exc:
        assert getattr(exc, 'error_type', None) == 'preflight'
        assert 'missing fixture' in str(exc)
    else:
        raise AssertionError('expected preflight failure')


def test_invalid_json_classified() -> None:
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / 'bad.json'
        path.write_text('{bad json')
        try:
            load_json_with_context(path)
        except StateParseError as exc:
            assert exc.error_type == 'state_parse'
        else:
            raise AssertionError('expected StateParseError')


def test_envelope_schema_and_retry() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        env = RunEnvelope(job_name='fixture', mode='test', runs_root=root / 'runs', workspace_root=root, run_id=make_run_id('fixture'))
        proc = env.run_subprocess_with_retries([sys.executable, '-c', 'print("ok")'], cwd=root, label='ok-command', attempts=2)
        assert proc.stdout.strip() == 'ok'
        env.finish(status='ok', summary_line='FIXTURE_OK', returncode=0)
        payload = json.loads(env.envelope_path.read_text())
        assert payload['schema_version'] == 'maintenance-run-envelope/v1'
        assert payload['status'] == 'ok'
        assert payload['summary_line'] == 'FIXTURE_OK'
        assert any('ok-command.attempt-1.stdout.txt' in item for item in payload['artifact_paths'])


def test_context_apply_dry_run_does_not_edit() -> None:
    proc = subprocess.run(
        [sys.executable, 'scripts/run_context_prune_maintenance.py', 'weekly-apply', '--dry-run', '--no-local-compress', '--stamp', 'fixture-dryrun-test'],
        cwd=str(ROOT / 'workbench-context-maintenance'),
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert proc.stdout.startswith('PRUNE_AUTO_APPLY_DRY_RUN_OK'), proc.stdout
    manifest = Path('/Users/agent2/.openclaw/workbench/tmp/context-archive/section-prune/fixture-dryrun-test/pre-apply-manifest.json')
    payload = json.loads(manifest.read_text())
    assert payload['mode'] == 'dry_run'
    assert 'files' in payload


def test_script_usage_self_check_validates_complete_fresh_join() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        usage_path = root / 'script-usage-summary.json'
        usage_md = root / 'script-usage-summary.md'
        classification_path = root / 'script-classification.json'
        usage_path.write_text(json.dumps({
            'schema_version': 'openclaw-script-usage-summary/v1',
            'phase': 'C4',
            'generated_at_utc': '2026-05-18T18:00:00Z',
            'summary': {
                'classified_script_count': 2,
                'parse_issue_count': 0,
                'unmatched_ledger_script_count': 0,
            },
            'scripts': [{'path': 'scripts/a.py'}, {'path': 'scripts/b.py'}],
        }))
        usage_md.write_text('# summary\n')
        classification_path.write_text(json.dumps({'records': [{'path': 'scripts/a.py'}, {'path': 'scripts/b.py'}]}))
        old_usage = maintenance_self_check.SCRIPT_USAGE_SUMMARY_JSON
        old_md = maintenance_self_check.SCRIPT_USAGE_SUMMARY_MD
        old_classification = maintenance_self_check.SCRIPT_CLASSIFICATION_JSON
        maintenance_self_check.SCRIPT_USAGE_SUMMARY_JSON = usage_path
        maintenance_self_check.SCRIPT_USAGE_SUMMARY_MD = usage_md
        maintenance_self_check.SCRIPT_CLASSIFICATION_JSON = classification_path
        try:
            checks: list[maintenance_self_check.Check] = []
            maintenance_self_check.check_script_usage_summary(
                checks,
                max_age_hours=2,
                now=maintenance_self_check.datetime.fromisoformat('2026-05-18T18:30:00+00:00'),
            )
        finally:
            maintenance_self_check.SCRIPT_USAGE_SUMMARY_JSON = old_usage
            maintenance_self_check.SCRIPT_USAGE_SUMMARY_MD = old_md
            maintenance_self_check.SCRIPT_CLASSIFICATION_JSON = old_classification
    assert checks == [maintenance_self_check.Check('script_usage_summary', 'ok', 'fresh complete join: scripts=2 generated_at=2026-05-18T18:00:00Z')]


def test_script_usage_self_check_rejects_incomplete_join() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        usage_path = root / 'script-usage-summary.json'
        usage_md = root / 'script-usage-summary.md'
        classification_path = root / 'script-classification.json'
        usage_path.write_text(json.dumps({
            'schema_version': 'openclaw-script-usage-summary/v1',
            'phase': 'C4',
            'generated_at_utc': '2026-05-18T18:00:00Z',
            'summary': {
                'classified_script_count': 3,
                'parse_issue_count': 1,
                'unmatched_ledger_script_count': 0,
            },
            'scripts': [{'path': 'scripts/a.py'}],
        }))
        usage_md.write_text('# summary\n')
        classification_path.write_text(json.dumps({'records': [{'path': 'scripts/a.py'}, {'path': 'scripts/b.py'}]}))
        old_usage = maintenance_self_check.SCRIPT_USAGE_SUMMARY_JSON
        old_md = maintenance_self_check.SCRIPT_USAGE_SUMMARY_MD
        old_classification = maintenance_self_check.SCRIPT_CLASSIFICATION_JSON
        maintenance_self_check.SCRIPT_USAGE_SUMMARY_JSON = usage_path
        maintenance_self_check.SCRIPT_USAGE_SUMMARY_MD = usage_md
        maintenance_self_check.SCRIPT_CLASSIFICATION_JSON = classification_path
        try:
            checks: list[maintenance_self_check.Check] = []
            maintenance_self_check.check_script_usage_summary(
                checks,
                max_age_hours=2,
                now=maintenance_self_check.datetime.fromisoformat('2026-05-18T18:30:00+00:00'),
            )
        finally:
            maintenance_self_check.SCRIPT_USAGE_SUMMARY_JSON = old_usage
            maintenance_self_check.SCRIPT_USAGE_SUMMARY_MD = old_md
            maintenance_self_check.SCRIPT_CLASSIFICATION_JSON = old_classification
    assert len(checks) == 1
    assert checks[0].name == 'script_usage_summary'
    assert checks[0].status == 'error'
    assert 'join_incomplete' in checks[0].detail
    assert 'classified_script_count_mismatch' in checks[0].detail
    assert 'parse_issue_count=1' in checks[0].detail


def test_maintenance_self_check_expects_script_cleanup_crons() -> None:
    assert 'Maintenance: Orchestrator Script Evidence Refresh' in maintenance_self_check.EXPECTED_JOBS
    assert 'Maintenance: Orchestrator Script Auto-Archive Apply' in maintenance_self_check.EXPECTED_JOBS
    assert 'Maintenance: Orchestrator Script Auto-Delete Apply' in maintenance_self_check.EXPECTED_JOBS


def test_maintenance_self_check_expects_pressure_check_cron() -> None:
    assert 'Maintenance: Workbench Context Prune Pressure Check' in maintenance_self_check.EXPECTED_JOBS


def test_maintenance_self_check_accepts_script_auto_archive_and_delete_cron_inventory() -> None:
    original_run = maintenance_self_check.subprocess.run
    jobs = [
        {
            'name': name,
            'agentId': 'maintenance',
            'failureAlert': {'after': 1},
            'state': {},
        }
        for name in maintenance_self_check.EXPECTED_JOBS
    ]
    class Proc:
        returncode = 0
        stdout = json.dumps({'jobs': jobs})
        stderr = ''
    try:
        maintenance_self_check.subprocess.run = lambda *args, **kwargs: Proc()
        checks = []
        maintenance_self_check.run_cron_check(checks)
    finally:
        maintenance_self_check.subprocess.run = original_run
    assert checks[-1].name == 'cron_inventory'
    assert checks[-1].status == 'ok'
    assert 'expected jobs present' in checks[-1].detail


def test_maintenance_self_check_rejects_missing_pressure_check_cron_inventory() -> None:
    jobs = [
        {
            'name': name,
            'agentId': 'maintenance',
            'failureAlert': {'after': 1},
            'state': {},
        }
        for name in maintenance_self_check.EXPECTED_JOBS
        if name != 'Maintenance: Workbench Context Prune Pressure Check'
    ]
    checks = []

    maintenance_self_check.run_cron_check(checks, {'jobs': jobs})

    assert checks[-1].name == 'cron_inventory'
    assert checks[-1].status == 'error'
    assert 'Maintenance: Workbench Context Prune Pressure Check' in checks[-1].detail


def test_objective_status_classifies_met_partial_degraded_and_no_action() -> None:
    assert objective_status_from_wrapper({'pressure_objective': {'hard_budget_met': True}}) == 'met'
    assert objective_status_from_wrapper({
        'pressure_objective': {
            'hard_budget_met': False,
            'changed_paths': ['context/active.md'],
            'remaining_hard_budget_paths': ['context/active.md'],
        }
    }) == 'partial'
    assert objective_status_from_wrapper({
        'pressure_objective': {
            'hard_budget_met': False,
            'remaining_hard_budget_paths': ['context/decisions.md'],
        }
    }) == 'degraded'
    assert objective_status_from_wrapper({'status': 'ok'}) == 'no_action_needed'


def test_objective_rollup_preserves_next_action_as_status_not_execution() -> None:
    rollup = build_objective_rollup(
        plane='workbench-pressure',
        scheduler_status='healthy',
        wrapper_status='completed',
        wrapper_result={
            'decisions_consolidation': {
                'decisions_backlog': {
                    'status': 'review_required',
                    'reason': 'repeated_insufficient_safe_shrink',
                    'recommended_action': 'manual_decisions_consolidation_review',
                    'repeated_count': 3,
                }
            }
        },
        generated_artifacts=['generated/decisions-consolidation/backlog-status.json'],
    )

    assert rollup['objective_status'] == 'degraded'
    assert rollup['mutation_count'] == 0
    assert rollup['destructive_action_count'] == 0
    assert 'decisions_backlog:repeated_insufficient_safe_shrink' in rollup['degraded_reasons']
    assert rollup['backlog_after']['recommended_action'] == 'manual_decisions_consolidation_review'


def test_self_check_objective_rollup_marks_missing_scheduler() -> None:
    rollups = maintenance_self_check.objective_rollups_from_cron_payload({'jobs': []})

    pressure = next(item for item in rollups if item['plane'] == 'Maintenance: Workbench Context Prune Pressure Check')
    assert pressure['scheduler_status'] == 'missing'
    assert pressure['objective_status'] == 'no_action_needed'


def test_cleanup_plan_uses_usage_aware_action_classes() -> None:
    summary = {
        'review_candidates': [
            {
                'path': 'scripts/recent.py',
                'classification': 'deprecated_candidate',
                'confidence': 'medium',
                'inbound_reference_count': 0,
                'script_usage': {'coverage_status': 'direct', 'run_count_total': 1, 'cleanup_eligibility_blockers': [], 'evidence_sources': ['ledger']},
            },
            {
                'path': 'scripts/referenced.py',
                'classification': 'deprecated_candidate',
                'confidence': 'medium',
                'inbound_reference_count': 0,
                'script_usage': {
                    'coverage_status': 'parent_observed',
                    'reference_evidence': [{'source_kind': 'operator_docs'}],
                    'cleanup_eligibility_blockers': ['has_operator_doc_reference'],
                    'evidence_sources': ['operator_docs'],
                },
            },
            {
                'path': 'scripts/unknown.py',
                'classification': 'deprecated_candidate',
                'confidence': 'medium',
                'inbound_reference_count': 0,
                'script_usage': {
                    'coverage_status': 'pre_instrumentation_unknown',
                    'cleanup_eligibility_blockers': ['pre_instrumentation_unknown', 'coverage_window_not_mature'],
                    'evidence_sources': ['static_inventory'],
                },
            },
        ],
        'script_classification': {},
        'lifecycle_overrides': {},
    }
    clutter = {'records': [{'path': '.DS_Store', 'category': 'macos_metadata', 'kind': 'file', 'cleanup_policy': 'safe_to_remove_after_git_status_check'}]}
    old_tracked = run_maintenance.git_tracked_paths
    run_maintenance.git_tracked_paths = lambda: set()
    try:
        plan = run_maintenance.build_cleanup_plan(summary, clutter)
    finally:
        run_maintenance.git_tracked_paths = old_tracked

    assert plan['schema_version'] == 'orchestrator-cleanup-plan/v2'
    assert 'retain_recently_used' in plan['summary']['usage_aware_action_classes']
    assert plan['clutter_actions'][0]['planned_action'] == 'auto_remove_clutter_ready'
    actions = {item['path']: item for item in plan['script_review_actions']}
    assert actions['scripts/recent.py']['planned_action'] == 'retain_recently_used'
    assert actions['scripts/referenced.py']['planned_action'] == 'retain_referenced'
    assert actions['scripts/unknown.py']['planned_action'] == 'manual_lifecycle_review'
    assert actions['scripts/unknown.py']['usage_cleanup']['coverage_status'] == 'pre_instrumentation_unknown'
    assert 'coverage_window_not_mature' in actions['scripts/unknown.py']['usage_cleanup']['cleanup_eligibility_blockers']


def test_cleanup_plan_blocks_approved_candidates_with_usage_blockers() -> None:
    summary = {
        'review_candidates': [
            {
                'path': 'scripts/approved-but-immature.py',
                'classification': 'deprecated_candidate',
                'confidence': 'high',
                'inbound_reference_count': 0,
                'lifecycle_override': {
                    'lifecycle_status': 'archive_approved',
                    'verification': {
                        'operator_docs_checked': True,
                        'launchd_cron_checked': True,
                        'external_usage_checked': True,
                        'runtime_state_checked': True,
                        'archive_path_defined': True,
                    },
                },
                'script_usage': {
                    'coverage_status': 'pre_instrumentation_unknown',
                    'cleanup_eligibility_blockers': ['pre_instrumentation_unknown', 'coverage_window_not_mature'],
                    'evidence_sources': ['static_inventory'],
                },
            }
        ]
    }
    old_tracked = run_maintenance.git_tracked_paths
    run_maintenance.git_tracked_paths = lambda: set()
    try:
        plan = run_maintenance.build_cleanup_plan(summary, {'records': []})
    finally:
        run_maintenance.git_tracked_paths = old_tracked
    item = plan['script_review_actions'][0]
    assert item['high_confidence']['eligible_for_archive'] is True
    assert item['planned_action'] == 'manual_lifecycle_review'
    assert item['reason'] == 'usage_coverage_not_mature'


def test_cleanup_plan_reports_gate_ready_and_blockers() -> None:
    summary = {
        'review_candidates': [
            {
                'path': 'scripts/archive-ready.py',
                'classification': 'deprecated_candidate',
                'confidence': 'high',
                'inbound_reference_count': 0,
                'lifecycle_override': {
                    'lifecycle_status': 'archive_approved',
                    'verification': {
                        'operator_docs_checked': True,
                        'launchd_cron_checked': True,
                        'external_usage_checked': True,
                        'runtime_state_checked': True,
                        'archive_path_defined': True,
                    },
                },
                'script_usage': {
                    'coverage_status': 'covered_no_observed_usage',
                    'cleanup_eligibility_blockers': [],
                    'evidence_sources': ['ledger', 'operator_docs'],
                },
            },
            {
                'path': 'scripts/blocked.py',
                'classification': 'deprecated_candidate',
                'confidence': 'medium',
                'inbound_reference_count': 0,
                'script_usage': {
                    'coverage_status': 'pre_instrumentation_unknown',
                    'cleanup_eligibility_blockers': ['coverage_window_not_mature'],
                    'evidence_sources': ['static_inventory'],
                },
            },
        ]
    }
    old_tracked = run_maintenance.git_tracked_paths
    run_maintenance.git_tracked_paths = lambda: set()
    try:
        plan = run_maintenance.build_cleanup_plan(summary, {'records': []})
    finally:
        run_maintenance.git_tracked_paths = old_tracked

    actions = {item['path']: item for item in plan['script_review_actions']}
    ready = actions['scripts/archive-ready.py']
    blocked = actions['scripts/blocked.py']
    assert plan['summary']['gate_evaluation_mode'] == 'report_only'
    assert plan['summary']['gate_ready_counts']['archive'] == 1
    assert plan['summary']['gate_ready_counts']['delete'] == 0
    assert ready['planned_action'] == 'auto_archive_ready'
    assert ready['reason'] == 'gate_evaluator_archive_ready_report_only'
    assert ready['cleanup_gate_evaluation']['archive']['ready'] is True
    assert ready['cleanup_gate_evaluation']['delete']['ready'] is False
    assert 'not_archived_for_one_cycle' in ready['cleanup_gate_evaluation']['delete']['blockers']
    assert blocked['cleanup_gate_evaluation']['archive']['ready'] is False
    assert 'usage:coverage_window_not_mature' in blocked['cleanup_gate_evaluation']['archive']['blockers']


def test_cleanup_plan_autonomously_promotes_archive_when_deterministic_evidence_is_clear() -> None:
    original_repo_root = run_maintenance.REPO_ROOT
    original_git_tracked_paths = run_maintenance.git_tracked_paths
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / 'orchestrator'
            script = repo / 'scripts' / 'retired.py'
            script.parent.mkdir(parents=True)
            script.write_text('print("retired")\n')
            run_maintenance.REPO_ROOT = repo.resolve()
            run_maintenance.git_tracked_paths = lambda: {'scripts/retired.py'}
            summary = {
                'review_candidates': [
                    {
                        'path': 'scripts/retired.py',
                        'classification': 'deprecated_candidate',
                        'confidence': 'medium',
                        'inbound_reference_count': 0,
                        'script_usage': {
                            'coverage_status': 'covered_no_observed_usage',
                            'cleanup_eligibility_blockers': [],
                            'evidence_sources': ['ledger'],
                            'run_count_total': 0,
                            'start_count': 0,
                            'reference_evidence': [],
                            'parent_callers': [],
                        },
                    }
                ]
            }
            plan = run_maintenance.build_cleanup_plan(summary, {'records': []})
    finally:
        run_maintenance.REPO_ROOT = original_repo_root
        run_maintenance.git_tracked_paths = original_git_tracked_paths
    item = plan['script_review_actions'][0]
    assert item['autonomous_archive_promotion']['eligible_for_auto_archive_promotion'] is True
    assert item['high_confidence']['eligible_for_archive'] is True
    assert item['cleanup_gate_evaluation']['archive']['ready'] is True
    assert item['planned_action'] == 'auto_archive_ready'
    assert plan['summary']['auto_archive_promotion']['eligible_count'] == 1



def test_cleanup_plan_blocks_missing_usage_summary_rows() -> None:
    summary = {
        'review_candidates': [
            {
                'path': 'scripts/missing-usage.py',
                'classification': 'deprecated_candidate',
                'confidence': 'medium',
                'inbound_reference_count': 0,
                'script_usage': {},
            }
        ]
    }
    old_tracked = run_maintenance.git_tracked_paths
    run_maintenance.git_tracked_paths = lambda: set()
    try:
        plan = run_maintenance.build_cleanup_plan(summary, {'records': []})
    finally:
        run_maintenance.git_tracked_paths = old_tracked
    item = plan['script_review_actions'][0]
    assert item['planned_action'] == 'manual_review_required'
    assert item['reason'] == 'missing_usage_summary_row'
    assert item['usage_cleanup']['coverage_status'] == 'missing_from_usage_summary'


def test_cleanup_candidate_history_tracks_repeated_no_use_state() -> None:
    cleanup_plan = {
        'script_review_actions': [
            {
                'path': 'scripts/no-use.py',
                'planned_action': 'manual_lifecycle_review',
                'classification': 'deprecated_candidate',
                'reason': 'usage_coverage_not_mature',
                'usage_cleanup': {
                    'usage_summary_available': True,
                    'observed_recently_or_directly': False,
                    'run_count_total': 0,
                    'coverage_status': 'covered_no_observed_usage',
                },
                'cleanup_gate_evaluation': {'archive': {'decision': 'blocked'}, 'delete': {'decision': 'blocked'}},
            }
        ],
        'summary': {},
    }
    first = run_maintenance.build_cleanup_candidate_history(cleanup_plan, {}, now_iso='2026-05-01T00:00:00Z')
    second = run_maintenance.build_cleanup_candidate_history(cleanup_plan, first, now_iso='2026-05-18T00:00:00Z')
    entry = second['candidates']['scripts/no-use.py']
    assert entry['consecutive_same_state_count'] == 2
    assert entry['consecutive_no_use_count'] == 2
    assert entry['total_no_use_observation_count'] == 2
    assert entry['observation_window']['no_use_days'] == 17
    assert entry['observation_window']['mature'] is False


def test_cleanup_candidate_history_marks_mature_after_window_and_observations() -> None:
    cleanup_plan = {
        'script_review_actions': [
            {
                'path': 'scripts/mature.py',
                'planned_action': 'archive_review_candidate',
                'classification': 'deprecated_candidate',
                'reason': 'deprecated_candidate_with_no_refs_after_usage_checks',
                'usage_cleanup': {
                    'usage_summary_available': True,
                    'observed_recently_or_directly': False,
                    'run_count_total': 0,
                    'coverage_status': 'covered_no_observed_usage',
                },
                'cleanup_gate_evaluation': {'archive': {'decision': 'blocked'}, 'delete': {'decision': 'blocked'}},
            }
        ],
        'summary': {},
    }
    first = run_maintenance.build_cleanup_candidate_history(cleanup_plan, {}, now_iso='2026-04-01T00:00:00Z')
    second = run_maintenance.build_cleanup_candidate_history(cleanup_plan, first, now_iso='2026-04-20T00:00:00Z')
    third = run_maintenance.build_cleanup_candidate_history(cleanup_plan, second, now_iso='2026-05-18T00:00:00Z')
    entry = third['candidates']['scripts/mature.py']
    assert entry['consecutive_same_state_count'] == 3
    assert entry['consecutive_no_use_count'] == 3
    assert entry['observation_window']['no_use_days'] == 47
    assert entry['observation_window']['mature'] is True
    attached = run_maintenance.attach_candidate_history(cleanup_plan, third)
    assert attached['script_review_actions'][0]['candidate_history']['observation_window']['mature'] is True
    assert attached['summary']['candidate_history']['mature_no_use_candidate_count'] == 1


def test_cleanup_candidate_history_resets_no_use_on_observed_usage() -> None:
    prior = {
        'candidates': {
            'scripts/used.py': {
                'candidate_state_key': 'old',
                'first_seen_at': '2026-04-01T00:00:00Z',
                'consecutive_no_use_count': 2,
                'total_no_use_observation_count': 2,
                'first_no_use_at': '2026-04-01T00:00:00Z',
            }
        }
    }
    cleanup_plan = {
        'script_review_actions': [
            {
                'path': 'scripts/used.py',
                'planned_action': 'retain_recently_used',
                'classification': 'deprecated_candidate',
                'reason': 'direct_ledger_usage_or_recent_observation',
                'usage_cleanup': {
                    'usage_summary_available': True,
                    'observed_recently_or_directly': True,
                    'run_count_total': 1,
                    'coverage_status': 'direct',
                },
                'cleanup_gate_evaluation': {'archive': {'decision': 'blocked'}, 'delete': {'decision': 'blocked'}},
            }
        ],
        'summary': {},
    }
    history = run_maintenance.build_cleanup_candidate_history(cleanup_plan, prior, now_iso='2026-05-18T00:00:00Z')
    entry = history['candidates']['scripts/used.py']
    assert entry['consecutive_no_use_count'] == 0
    assert entry['total_no_use_observation_count'] == 2
    assert entry['observation_window']['mature'] is False



def test_scheduled_cleanup_delete_readiness_guard_blocks_delete_ready() -> None:
    cleanup_plan = {
        'summary': {'gate_ready_counts': {'delete': 1}},
        'script_review_actions': [
            {
                'path': 'scripts/delete-ready.py',
                'planned_action': 'auto_delete_ready',
                'cleanup_gate_evaluation': {'delete': {'ready': True}},
            }
        ],
    }
    guard = run_scheduled_maintenance.cleanup_delete_readiness_guard(cleanup_plan)
    assert guard['mode'] == 'report_only'
    assert guard['ok'] is False
    assert guard['premature_delete_ready_count'] == 1
    assert guard['planned_delete_ready_paths'] == ['scripts/delete-ready.py']
    assert guard['gate_delete_ready_paths'] == ['scripts/delete-ready.py']


def test_scheduled_cleanup_delete_readiness_guard_allows_current_zero_delete_ready() -> None:
    cleanup_plan = {
        'summary': {'gate_ready_counts': {'archive': 0, 'delete': 0}},
        'script_review_actions': [
            {
                'path': 'scripts/manual.py',
                'planned_action': 'manual_lifecycle_review',
                'cleanup_gate_evaluation': {'delete': {'ready': False}},
            }
        ],
    }
    guard = run_scheduled_maintenance.cleanup_delete_readiness_guard(cleanup_plan)
    assert guard['ok'] is True
    assert guard['premature_delete_ready_count'] == 0
    assert guard['gate_ready_delete_count'] == 0


def test_scheduled_confidence_stage_accepts_usage_aware_ready_actions() -> None:
    assert run_scheduled_maintenance.confidence_stage('auto_archive_ready', 1, []) == 'high_confidence_archive_ready'
    assert run_scheduled_maintenance.confidence_stage('auto_delete_ready', 1, []) == 'high_confidence_removal_ready'
    assert run_scheduled_maintenance.confidence_score('auto_archive_ready', 1, []) == 90
    assert run_scheduled_maintenance.confidence_score('auto_delete_ready', 1, []) == 100



def test_cleanup_evidence_diff_suppresses_counter_only_noise() -> None:
    previous_plan = {
        'summary': {'action_counts': {'manual_lifecycle_review': 1}, 'gate_ready_counts': {'archive': 0, 'delete': 0}},
        'script_review_actions': [
            {
                'path': 'scripts/stable.py',
                'planned_action': 'manual_lifecycle_review',
                'reason': 'usage_coverage_not_mature',
                'cleanup_gate_evaluation': {'archive': {'blockers': ['usage:coverage_window_not_mature']}, 'delete': {'blockers': ['usage:coverage_window_not_mature']}},
            }
        ],
    }
    current_plan = json.loads(json.dumps(previous_plan))
    previous_history = {'candidates': {'scripts/stable.py': {'observation_window': {'mature': False}, 'consecutive_same_state_count': 1}}}
    current_history = {'candidates': {'scripts/stable.py': {'observation_window': {'mature': False}, 'consecutive_same_state_count': 2}}}
    diff = run_maintenance.build_cleanup_evidence_diff(current_plan, previous_plan, current_history, previous_history)
    assert diff['baseline_available'] is True
    assert diff['meaningful_change_count'] == 0
    assert diff['action_changed_paths'] == []
    assert diff['blocker_changed_paths'] == []


def test_cleanup_evidence_diff_reports_action_and_maturity_changes() -> None:
    previous_plan = {
        'summary': {'action_counts': {'manual_lifecycle_review': 1}, 'gate_ready_counts': {'archive': 0, 'delete': 0}},
        'script_review_actions': [
            {
                'path': 'scripts/candidate.py',
                'planned_action': 'manual_lifecycle_review',
                'reason': 'usage_coverage_not_mature',
                'cleanup_gate_evaluation': {'archive': {'blockers': ['usage:coverage_window_not_mature']}, 'delete': {'blockers': ['usage:coverage_window_not_mature']}},
            }
        ],
    }
    current_plan = {
        'summary': {'action_counts': {'archive_review_candidate': 1}, 'gate_ready_counts': {'archive': 0, 'delete': 0}},
        'script_review_actions': [
            {
                'path': 'scripts/candidate.py',
                'planned_action': 'archive_review_candidate',
                'reason': 'deprecated_candidate_with_no_refs_after_usage_checks',
                'cleanup_gate_evaluation': {'archive': {'blockers': []}, 'delete': {'blockers': ['not_archived_for_one_cycle']}},
            }
        ],
    }
    previous_history = {'candidates': {'scripts/candidate.py': {'observation_window': {'mature': False}}}}
    current_history = {'candidates': {'scripts/candidate.py': {'observation_window': {'mature': True}}}}
    diff = run_maintenance.build_cleanup_evidence_diff(current_plan, previous_plan, current_history, previous_history)
    assert diff['meaningful_change_count'] >= 1
    assert diff['action_changed_paths'] == ['scripts/candidate.py']
    assert diff['blocker_changed_paths'] == ['scripts/candidate.py']
    assert diff['new_mature_no_use_paths'] == ['scripts/candidate.py']
    assert diff['action_count_delta']['archive_review_candidate']['delta'] == 1
    assert diff['action_count_delta']['manual_lifecycle_review']['delta'] == -1


def test_script_cleanup_blocker_report_assigns_autonomous_next_actions() -> None:
    cleanup_plan = {
        'script_review_actions': [
            {
                'path': 'scripts/unknown.py',
                'classification': 'deprecated_candidate',
                'planned_action': 'manual_lifecycle_review',
                'reason': 'usage_coverage_not_mature',
                'usage_cleanup': {
                    'coverage_status': 'pre_instrumentation_unknown',
                    'cleanup_eligibility_blockers': [
                        'pre_instrumentation_unknown',
                        'no_observed_ledger_usage',
                        'coverage_window_not_mature',
                    ],
                },
                'cleanup_gate_evaluation': {
                    'archive': {
                        'ready': False,
                        'blockers': [
                            'usage:pre_instrumentation_unknown',
                            'verification:no_static_inbound_refs',
                            'verification:removal_eligible_class',
                            'lifecycle_not_archive_approved',
                        ],
                    },
                    'delete': {
                        'ready': False,
                        'blockers': ['usage:pre_instrumentation_unknown', 'lifecycle_not_removal_approved'],
                    },
                },
            }
        ]
    }
    usage_summary = {
        'summary': {'pre_instrumentation_unknown_count': 1},
        'scripts': [
            {
                'path': 'scripts/unknown.py',
                'coverage_status': 'pre_instrumentation_unknown',
                'evidence_sources': ['static_inventory'],
            }
        ],
    }

    report = run_maintenance.build_script_cleanup_blocker_report(cleanup_plan, usage_summary)

    assert report['manual_owner_review_required_count'] == 0
    assert report['autonomous_next_action_count'] > 0
    assert report['ready_candidate_slo']['met'] is True
    assert report['next_actions_by_lane']['Maintenance: Orchestrator Script Evidence Refresh']['autonomous'] is True
    record = report['records'][0]
    assert all(action['autonomous'] for action in record['next_actions'])
    assert {action['action'] for action in record['next_actions']} >= {
        'refresh_usage_reference_and_runtime_evidence',
        'rerun_deterministic_archive_promotion_checks',
    }


def test_script_cleanup_evidence_movement_reports_autonomous_progress() -> None:
    previous_usage = {
        'scripts': [
            {'path': 'scripts/a.py', 'coverage_status': 'pre_instrumentation_unknown'},
            {'path': 'scripts/b.py', 'coverage_status': 'pre_instrumentation_unknown'},
        ]
    }
    current_usage = {
        'scripts': [
            {'path': 'scripts/a.py', 'coverage_status': 'direct'},
            {'path': 'scripts/b.py', 'coverage_status': 'parent_observed', 'evidence_sources': ['operator_docs']},
        ]
    }
    previous_plan = {
        'script_review_actions': [
            {'path': 'scripts/a.py', 'planned_action': 'manual_lifecycle_review'},
            {'path': 'scripts/b.py', 'planned_action': 'manual_lifecycle_review'},
        ],
    }
    current_plan = {
        'summary': {'gate_ready_counts': {'archive': 1, 'delete': 0}},
        'script_review_actions': [
            {'path': 'scripts/b.py', 'planned_action': 'retain_referenced'},
        ],
    }
    previous_blockers = {'blocker_counts': {'usage:pre_instrumentation_unknown': 2}}
    current_blockers = {
        'blocker_counts': {'usage:pre_instrumentation_unknown': 1},
        'autonomous_next_action_count': 1,
        'next_actions_by_lane': {'Maintenance: Orchestrator Script Evidence Refresh': {'count': 1, 'autonomous': True}},
    }

    movement = run_maintenance.build_script_cleanup_evidence_movement(
        previous_usage,
        current_usage,
        previous_plan,
        current_plan,
        previous_blockers,
        current_blockers,
    )

    assert movement['throughput_status'] == 'evidence_moved'
    assert movement['unknown_reduced_count'] == 2
    assert movement['new_observed_count'] == 1
    assert movement['new_referenced_count'] == 1
    assert movement['ready_candidate_count'] == 1
    assert movement['retired_candidate_count'] == 2
    assert movement['blocker_retired_count'] == 1
    assert movement['zero_archive_delete_throughput_acceptable'] is True


def test_scheduled_script_evidence_refresh_blocks_only_unowned_actions() -> None:
    summary = {
        'script_classification': {'script_count': 2},
        'review_candidate_count': 1,
        'cleanup_plan': {
            'high_confidence_archive_count': 0,
            'high_confidence_removal_count': 0,
            'action_counts': {'manual_lifecycle_review': 1},
        },
    }
    blockers = {
        'autonomous_next_action_count': 3,
        'manual_owner_review_required_count': 0,
        'ready_candidate_slo': {'met': True},
        'next_actions_by_lane': {'Maintenance: Orchestrator Script Evidence Refresh': {'count': 3, 'autonomous': True}},
    }
    movement = {
        'throughput_status': 'waiting_on_autonomous_next_actions',
        'zero_archive_delete_throughput_acceptable': True,
    }

    ok_result = run_scheduled_maintenance.build_script_evidence_refresh_result(summary, blockers, movement)
    assert ok_result['ok'] is True
    assert ok_result['status'] == 'completed'

    blocked_result = run_scheduled_maintenance.build_script_evidence_refresh_result(
        summary,
        {**blockers, 'manual_owner_review_required_count': 1},
        {'throughput_status': 'owner_review_required'},
    )
    assert blocked_result['ok'] is False
    assert blocked_result['blocked_reason'] == 'unowned_cleanup_next_actions'



def test_clutter_apply_dry_run_includes_only_trivial_untracked_clutter() -> None:
    cleanup_plan = {
        'clutter_actions': [
            {'path': '.DS_Store', 'category': 'macos_metadata', 'kind': 'file', 'tracked_by_git': False, 'planned_action': 'auto_remove_clutter_ready', 'reason': 'macos_metadata_untracked'},
            {'path': 'scripts/__pycache__', 'category': 'python_bytecode_cache', 'kind': 'directory', 'tracked_by_git': False, 'planned_action': 'auto_remove_clutter_ready', 'reason': 'python_bytecode_cache_untracked_after_process_check'},
            {'path': 'scripts/.runtime-state', 'category': 'runtime_state', 'kind': 'directory', 'tracked_by_git': False, 'planned_action': 'manual_review_only', 'reason': 'runtime_state_may_be_live_or_diagnostic'},
            {'path': 'tracked/.DS_Store', 'category': 'macos_metadata', 'kind': 'file', 'tracked_by_git': True, 'planned_action': 'blocked', 'reason': 'tracked_by_git'},
        ]
    }
    dry_run = run_maintenance.build_clutter_apply_dry_run(cleanup_plan)
    assert dry_run['mode'] == 'dry_run_only'
    assert dry_run['mutating'] is False
    assert dry_run['operation_count'] == 2
    assert dry_run['excluded_count'] == 2
    operations = {item['path']: item for item in dry_run['operations']}
    assert operations['.DS_Store']['dry_run_action'] == 'would_remove_file'
    assert operations['.DS_Store']['apply_slice'] == 'E2'
    assert operations['scripts/__pycache__']['dry_run_action'] == 'would_remove_directory_after_process_check'
    assert operations['scripts/__pycache__']['apply_slice'] == 'E3'
    assert 'no_live_python_process_using_tree' in operations['scripts/__pycache__']['required_preflight']


def test_clutter_apply_dry_run_excludes_runtime_and_unknown_clutter() -> None:
    cleanup_plan = {
        'clutter_actions': [
            {'path': 'runtime/state', 'category': 'runtime_state', 'kind': 'directory', 'tracked_by_git': False, 'planned_action': 'manual_review_only', 'reason': 'runtime_state_may_be_live_or_diagnostic'},
            {'path': 'mystery.tmp', 'category': 'unknown', 'kind': 'file', 'tracked_by_git': False, 'planned_action': 'blocked', 'reason': 'unknown_clutter_category'},
        ]
    }
    dry_run = run_maintenance.build_clutter_apply_dry_run(cleanup_plan)
    assert dry_run['operation_count'] == 0
    assert dry_run['excluded_count'] == 2
    assert {item['category'] for item in dry_run['excluded']} == {'runtime_state', 'unknown'}



def test_git_status_confirms_only_untracked_or_ignored_exact_path() -> None:
    assert run_maintenance.git_status_confirms_untracked_or_ignored(['?? .DS_Store'], '.DS_Store')
    assert run_maintenance.git_status_confirms_untracked_or_ignored(['!! nested/.DS_Store'], 'nested/.DS_Store')
    assert run_maintenance.git_status_confirms_untracked_or_ignored(['!! orchestrator/.DS_Store'], '.DS_Store', 'orchestrator/')
    assert not run_maintenance.git_status_confirms_untracked_or_ignored([' M .DS_Store'], '.DS_Store')
    assert not run_maintenance.git_status_confirms_untracked_or_ignored(['?? other/.DS_Store'], '.DS_Store')
    assert not run_maintenance.git_status_confirms_untracked_or_ignored([], '.DS_Store')


def test_build_ds_store_apply_result_skips_non_e2_operations(monkeypatch=None) -> None:
    dry_run = {
        'operations': [
            {'path': '.DS_Store', 'category': 'macos_metadata', 'kind': 'file', 'apply_slice': 'E2'},
            {'path': 'scripts/__pycache__', 'category': 'python_bytecode_cache', 'kind': 'directory', 'apply_slice': 'E3'},
        ]
    }
    original_status = run_maintenance.git_status_lines_for_path
    original_prefix = run_maintenance.git_status_path_prefix
    original_safe = run_maintenance.safe_repo_relative_path
    try:
        run_maintenance.git_status_lines_for_path = lambda path: ['!! ' + path]
        run_maintenance.git_status_path_prefix = lambda: ''
        run_maintenance.safe_repo_relative_path = lambda path: Path('/definitely/absent/.DS_Store')
        result = run_maintenance.build_ds_store_apply_result(dry_run, apply=False)
    finally:
        run_maintenance.git_status_lines_for_path = original_status
        run_maintenance.git_status_path_prefix = original_prefix
        run_maintenance.safe_repo_relative_path = original_safe
    assert result['mode'] == 'dry_run_only'
    assert result['mutating'] is False
    assert result['would_remove_count'] == 0
    assert result['skipped_count'] == 2
    assert {item['reason'] for item in result['skipped']} == {'already_absent', 'not_e2_ds_store_operation'}



def test_git_status_confirms_untracked_or_ignored_tree_entries() -> None:
    lines = [
        '!! orchestrator/scripts/__pycache__/a.pyc',
        '!! orchestrator/scripts/__pycache__/b.pyc',
    ]
    assert run_maintenance.git_status_confirms_tree_untracked_or_ignored(lines, 'scripts/__pycache__', 'orchestrator/')
    assert not run_maintenance.git_status_confirms_tree_untracked_or_ignored([' M orchestrator/scripts/__pycache__/a.pyc'], 'scripts/__pycache__', 'orchestrator/')
    assert not run_maintenance.git_status_confirms_tree_untracked_or_ignored(['!! orchestrator/other/__pycache__/a.pyc'], 'scripts/__pycache__', 'orchestrator/')


def test_build_pycache_apply_result_requires_no_live_python_process() -> None:
    dry_run = {
        'operations': [
            {'path': 'scripts/__pycache__', 'category': 'python_bytecode_cache', 'kind': 'directory', 'apply_slice': 'E3'},
            {'path': '.DS_Store', 'category': 'macos_metadata', 'kind': 'file', 'apply_slice': 'E2'},
        ]
    }
    with tempfile.TemporaryDirectory() as tmpdir:
        target = Path(tmpdir) / '__pycache__'
        target.mkdir()
        original_status = run_maintenance.git_status_lines_for_path
        original_prefix = run_maintenance.git_status_path_prefix
        original_safe = run_maintenance.safe_repo_relative_path
        original_live = run_maintenance.live_python_processes_using_tree
        try:
            run_maintenance.git_status_lines_for_path = lambda path: ['!! ' + path + '/a.pyc']
            run_maintenance.git_status_path_prefix = lambda: ''
            run_maintenance.safe_repo_relative_path = lambda path: target
            run_maintenance.live_python_processes_using_tree = lambda path: [{'pid': '123', 'source': 'ps'}]
            result = run_maintenance.build_pycache_apply_result(dry_run, apply=False)
        finally:
            run_maintenance.git_status_lines_for_path = original_status
            run_maintenance.git_status_path_prefix = original_prefix
            run_maintenance.safe_repo_relative_path = original_safe
            run_maintenance.live_python_processes_using_tree = original_live
    assert result['phase'] == 'E3'
    assert result['mutating'] is False
    assert result['would_remove_count'] == 0
    assert result['skipped_count'] == 2
    assert {item['reason'] for item in result['skipped']} == {'live_python_process_using_tree', 'not_e3_pycache_operation'}



def test_generated_run_retention_keeps_latest_and_selects_oldest() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        names = [
            'orchestrator-repo-20260515T154316Z-aaaa',
            'orchestrator-repo-20260515T155141Z-bbbb',
            'orchestrator-repo-20260518T192955Z-cccc',
            'orchestrator-repo-20260518T200000Z-dddd',
        ]
        dirs = []
        for name in names:
            path = root / name
            path.mkdir()
            dirs.append(path)
        selected = run_maintenance.select_generated_run_retention(dirs, keep_latest=2)
    assert [path.name for path in selected['protected']] == ['orchestrator-repo-20260518T200000Z-dddd', 'orchestrator-repo-20260518T192955Z-cccc']
    assert [path.name for path in selected['removable']] == ['orchestrator-repo-20260515T155141Z-bbbb', 'orchestrator-repo-20260515T154316Z-aaaa']


def test_generated_artifact_retention_result_protects_status_outputs() -> None:
    result = run_maintenance.build_generated_artifact_retention_result(apply=False, keep_latest=999)
    assert result['phase'] == 'E4'
    assert result['mutating'] is False
    assert result['removed_count'] == 0
    protected = set(result['protected_latest_status_outputs'])
    assert 'orchestrator-repo-maintenance/generated/maintenance-summary.json' in protected
    assert 'orchestrator-repo-maintenance/generated/cleanup-plan.json' in protected
    assert result['approved_roots'] == ['orchestrator-repo-maintenance/generated/runs']



def test_post_apply_verification_passes_with_self_check_and_repo_health() -> None:
    original_self_check = run_maintenance.run_maintenance_self_check
    original_load = run_maintenance.load_json_if_exists
    try:
        run_maintenance.run_maintenance_self_check = lambda: {
            'returncode': 0,
            'payload': {'overall_status': 'ok', 'summary': {'ok': 12, 'warning': 0, 'error': 0}},
        }
        run_maintenance.load_json_if_exists = lambda path: {'schema_version': 'orchestrator-repo-health-summary/v1', 'overall_band': 'needs_attention', 'overall_score': 43.0}
        result = run_maintenance.build_post_apply_verification_result('generated_retention', {'removed_count': 2})
    finally:
        run_maintenance.run_maintenance_self_check = original_self_check
        run_maintenance.load_json_if_exists = original_load
    assert result['phase'] == 'E5'
    assert result['ok'] is True
    assert result['self_check']['overall_status'] == 'ok'
    assert result['repo_health']['overall_band'] == 'needs_attention'


def test_post_apply_verification_fails_on_self_check_error() -> None:
    original_self_check = run_maintenance.run_maintenance_self_check
    original_load = run_maintenance.load_json_if_exists
    try:
        run_maintenance.run_maintenance_self_check = lambda: {
            'returncode': 1,
            'payload': {'overall_status': 'error', 'summary': {'ok': 10, 'warning': 0, 'error': 1}},
        }
        run_maintenance.load_json_if_exists = lambda path: {'schema_version': 'orchestrator-repo-health-summary/v1', 'overall_band': 'watch', 'overall_score': 70.0}
        result = run_maintenance.build_post_apply_verification_result('pycache_clutter', {'removed_count': 2})
    finally:
        run_maintenance.run_maintenance_self_check = original_self_check
        run_maintenance.load_json_if_exists = original_load
    assert result['ok'] is False
    assert result['checks'][0]['status'] == 'error'



def test_archive_layout_contract_defines_tombstone_and_restore() -> None:
    payload = run_maintenance.build_archive_layout_contract()
    assert payload['phase'] == 'F1'
    assert payload['mode'] == 'contract_only'
    assert payload['mutating'] is False
    assert payload['archive_root'] == 'orchestrator-repo-maintenance/archive/scripts'
    required = set(payload['tombstone_schema']['required_fields'])
    assert {'source_path', 'archive_path', 'source_sha256', 'restore_command', 'cleanup_gate_evaluation'} <= required
    assert payload['restore_command_format'].endswith('--restore-archived-script <tombstone-json-path>')


def test_archive_relative_path_is_stable_and_path_safe() -> None:
    first = run_maintenance.archive_relative_path('scripts/example.py', '20260518T000000Z')
    second = run_maintenance.archive_relative_path('scripts/example.py', '20260518T000000Z')
    other = run_maintenance.archive_relative_path('scripts/other.py', '20260518T000000Z')
    assert first == second
    assert first != other
    assert first.startswith('20260518T000000Z/scripts__example.py.')
    assert '/' in first and 'scripts/example.py' not in first



def test_archive_dry_run_only_proposes_fully_gated_candidates() -> None:
    cleanup_plan = {
        'script_review_actions': [
            {
                'path': 'scripts/ready.py',
                'planned_action': 'auto_archive_ready',
                'reason': 'approved_no_use',
                'cleanup_gate_evaluation': {'archive': {'ready': True, 'blockers': []}},
                'usage_cleanup': {'cleanup_eligibility_blockers': []},
            },
            {
                'path': 'scripts/blocked.py',
                'planned_action': 'manual_lifecycle_review',
                'cleanup_gate_evaluation': {'archive': {'ready': False, 'blockers': ['usage:coverage_window_not_mature']}},
            },
        ]
    }
    layout = {'schema_version': 'orchestrator-script-archive-layout/v1', 'archive_root': 'orchestrator-repo-maintenance/archive/scripts'}
    original_safe = run_maintenance.safe_repo_relative_path
    original_hash = run_maintenance.file_sha256
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / 'ready.py'
            source.write_text('print(1)\n')
            run_maintenance.safe_repo_relative_path = lambda path: source
            run_maintenance.file_sha256 = lambda path: 'abc123'
            dry = run_maintenance.build_archive_dry_run(cleanup_plan, layout, '20260518T000000Z')
    finally:
        run_maintenance.safe_repo_relative_path = original_safe
        run_maintenance.file_sha256 = original_hash
    assert dry['phase'] == 'F2'
    assert dry['mutating'] is False
    assert dry['proposal_count'] == 1
    assert dry['blocked_count'] == 1
    assert dry['proposals'][0]['source_path'] == 'scripts/ready.py'
    assert dry['proposals'][0]['restore_command'].endswith('.tombstone.json')


def test_archive_dry_run_blocks_ready_candidate_when_source_missing() -> None:
    cleanup_plan = {
        'script_review_actions': [
            {
                'path': 'scripts/missing.py',
                'planned_action': 'auto_archive_ready',
                'cleanup_gate_evaluation': {'archive': {'ready': True, 'blockers': []}},
            }
        ]
    }
    layout = {'schema_version': 'orchestrator-script-archive-layout/v1', 'archive_root': 'orchestrator-repo-maintenance/archive/scripts'}
    original_safe = run_maintenance.safe_repo_relative_path
    try:
        run_maintenance.safe_repo_relative_path = lambda path: Path('/definitely/missing.py')
        dry = run_maintenance.build_archive_dry_run(cleanup_plan, layout, '20260518T000000Z')
    finally:
        run_maintenance.safe_repo_relative_path = original_safe
    assert dry['proposal_count'] == 0
    assert dry['blocked_count'] == 1
    assert dry['blocked'][0]['reason'] == 'source_missing_or_not_file'



def test_script_archive_apply_noops_when_no_ready_proposals() -> None:
    dry = {'proposals': [], 'blocked': [{'reason': 'archive_gate_not_fully_ready'}]}
    result = run_maintenance.build_script_archive_apply_result(dry, apply=True)
    assert result['phase'] == 'F3'
    assert result['mutating'] is False
    assert result['archived_count'] == 0
    assert result['skipped_count'] == 1
    assert result['skipped'][0]['reason'] == 'no_ready_archive_proposals'


def test_script_archive_apply_moves_one_candidate_and_writes_tombstone() -> None:
    original_repo_root = run_maintenance.REPO_ROOT
    original_maintenance_dir = run_maintenance.MAINTENANCE_DIR
    original_archive_root = run_maintenance.SCRIPT_ARCHIVE_ROOT
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / 'orchestrator'
            source = repo / 'scripts' / 'ready.py'
            source.parent.mkdir(parents=True)
            source.write_text('print("ready")\n')
            maintenance_dir = root / 'maintenance' / 'orchestrator-repo-maintenance'
            archive_root = maintenance_dir / 'archive' / 'scripts'
            maintenance_dir.mkdir(parents=True)
            run_maintenance.REPO_ROOT = repo.resolve()
            run_maintenance.MAINTENANCE_DIR = maintenance_dir.resolve()
            run_maintenance.SCRIPT_ARCHIVE_ROOT = archive_root.resolve()
            cleanup_plan = {
                'script_review_actions': [
                    {
                        'path': 'scripts/ready.py',
                        'planned_action': 'auto_archive_ready',
                        'reason': 'approved_no_use',
                        'cleanup_gate_evaluation': {'archive': {'ready': True, 'blockers': []}},
                        'usage_cleanup': {'cleanup_eligibility_blockers': []},
                    }
                ]
            }
            layout = {'schema_version': 'orchestrator-script-archive-layout/v1', 'archive_root': 'orchestrator-repo-maintenance/archive/scripts'}
            dry = run_maintenance.build_archive_dry_run(cleanup_plan, layout, '20260518T000000Z')
            result = run_maintenance.build_script_archive_apply_result(dry, apply=True)
            archived = Path(root / 'maintenance' / result['archived'][0]['archive_path'])
            tombstone = Path(root / 'maintenance' / result['archived'][0]['tombstone_path'])
            assert result['mutating'] is True
            assert result['archived_count'] == 1
            assert not source.exists()
            assert archived.exists()
            assert tombstone.exists()
            payload = json.loads(tombstone.read_text())
            assert payload['schema_version'] == 'orchestrator-script-archive-tombstone/v1'
            assert payload['source_path'] == 'scripts/ready.py'
            assert payload['source_sha256'] == run_maintenance.file_sha256(archived)
    finally:
        run_maintenance.REPO_ROOT = original_repo_root
        run_maintenance.MAINTENANCE_DIR = original_maintenance_dir
        run_maintenance.SCRIPT_ARCHIVE_ROOT = original_archive_root



def test_post_archive_smoke_passes_no_archived_paths_with_refreshed_outputs() -> None:
    original_compile = run_maintenance.py_compile_check
    original_self_check = run_maintenance.run_maintenance_self_check
    original_load = run_maintenance.load_json_if_exists
    try:
        def fake_load(path: Path) -> dict:
            if path == run_maintenance.SCRIPT_CLASSIFICATION_JSON:
                return {'schema_version': 'orchestrator-script-classification/v1', 'summary': {'script_count': 12}}
            if path == run_maintenance.CLEANUP_PLAN_JSON:
                return {'schema_version': 'orchestrator-cleanup-plan/v2'}
            return {}
        run_maintenance.py_compile_check = lambda paths: {'returncode': 0, 'path_count': len(paths), 'stdout_tail': '', 'stderr_tail': ''}
        run_maintenance.run_maintenance_self_check = lambda: {'returncode': 0, 'payload': {'overall_status': 'ok', 'summary': {'ok': 12, 'warning': 0, 'error': 0}}}
        run_maintenance.load_json_if_exists = fake_load
        result = run_maintenance.build_post_archive_smoke_result({'archived': [], 'archived_count': 0, 'skipped_count': 1})
    finally:
        run_maintenance.py_compile_check = original_compile
        run_maintenance.run_maintenance_self_check = original_self_check
        run_maintenance.load_json_if_exists = original_load
    assert result['phase'] == 'F4'
    assert result['mutating'] is False
    assert result['ok'] is True
    assert any(item['name'] == 'touched_surface_smoke' and item['status'] == 'ok' for item in result['checks'])


def test_archived_touched_surface_checks_validate_tombstone_hash() -> None:
    original_repo_root = run_maintenance.REPO_ROOT
    original_maintenance_dir = run_maintenance.MAINTENANCE_DIR
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / 'orchestrator'
            repo.mkdir()
            maintenance_dir = root / 'maintenance' / 'orchestrator-repo-maintenance'
            archive = maintenance_dir / 'archive' / 'scripts' / '20260518T000000Z' / 'scripts__ready.py.abc'
            tombstone = Path(f'{archive}.tombstone.json')
            archive.parent.mkdir(parents=True)
            archive.write_text('print("archived")\n')
            digest = run_maintenance.file_sha256(archive)
            tombstone.write_text(json.dumps({'source_sha256': digest}) + '\n')
            run_maintenance.REPO_ROOT = repo.resolve()
            run_maintenance.MAINTENANCE_DIR = maintenance_dir.resolve()
            result = run_maintenance.archived_touched_surface_checks({
                'archived': [
                    {
                        'source_path': 'scripts/ready.py',
                        'archive_path': 'orchestrator-repo-maintenance/archive/scripts/20260518T000000Z/scripts__ready.py.abc',
                        'tombstone_path': 'orchestrator-repo-maintenance/archive/scripts/20260518T000000Z/scripts__ready.py.abc.tombstone.json',
                    }
                ]
            })
    finally:
        run_maintenance.REPO_ROOT = original_repo_root
        run_maintenance.MAINTENANCE_DIR = original_maintenance_dir
    statuses = {(item['name'], item['status']) for item in result}
    assert ('source_removed_after_archive', 'ok') in statuses
    assert ('archive_file_exists', 'ok') in statuses
    assert ('tombstone_exists', 'ok') in statuses or any(item['name'] == 'archive_hash_matches_tombstone' and item['status'] == 'ok' for item in result)
    assert any(item['name'] == 'archive_hash_matches_tombstone' and item['status'] == 'ok' for item in result)



def test_quarantine_monitor_empty_archive_is_clean_noop() -> None:
    original_archive_root = run_maintenance.SCRIPT_ARCHIVE_ROOT
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            run_maintenance.SCRIPT_ARCHIVE_ROOT = Path(tmpdir) / 'archive' / 'scripts'
            result = run_maintenance.build_quarantine_monitor_result({}, {'ok': True})
    finally:
        run_maintenance.SCRIPT_ARCHIVE_ROOT = original_archive_root
    assert result['phase'] == 'F5'
    assert result['mutating'] is False
    assert result['ok'] is True
    assert result['archived_script_count'] == 0
    assert result['restore_required_count'] == 0


def test_quarantine_monitor_tracks_clean_cycle_for_archived_script() -> None:
    original_repo_root = run_maintenance.REPO_ROOT
    original_maintenance_dir = run_maintenance.MAINTENANCE_DIR
    original_archive_root = run_maintenance.SCRIPT_ARCHIVE_ROOT
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / 'orchestrator'
            repo.mkdir()
            maintenance_dir = root / 'maintenance' / 'orchestrator-repo-maintenance'
            archive_root = maintenance_dir / 'archive' / 'scripts'
            archive = archive_root / '20260518T000000Z' / 'scripts__ready.py.abc'
            tombstone = Path(f'{archive}.tombstone.json')
            archive.parent.mkdir(parents=True)
            archive.write_text('print("archived")\n')
            digest = run_maintenance.file_sha256(archive)
            tombstone.write_text(json.dumps({
                'schema_version': 'orchestrator-script-archive-tombstone/v1',
                'source_path': 'scripts/ready.py',
                'archive_path': 'orchestrator-repo-maintenance/archive/scripts/20260518T000000Z/scripts__ready.py.abc',
                'source_sha256': digest,
                'archived_at_utc': '2026-05-18T00:00:00Z',
            }) + '\n')
            run_maintenance.REPO_ROOT = repo.resolve()
            run_maintenance.MAINTENANCE_DIR = maintenance_dir.resolve()
            run_maintenance.SCRIPT_ARCHIVE_ROOT = archive_root.resolve()
            previous = {'records': [{'source_path': 'scripts/ready.py', 'clean_cycle_count': 2}]}
            result = run_maintenance.build_quarantine_monitor_result(previous, {'ok': True})
    finally:
        run_maintenance.REPO_ROOT = original_repo_root
        run_maintenance.MAINTENANCE_DIR = original_maintenance_dir
        run_maintenance.SCRIPT_ARCHIVE_ROOT = original_archive_root
    assert result['ok'] is True
    assert result['archived_script_count'] == 1
    assert result['records'][0]['clean'] is True
    assert result['records'][0]['clean_cycle_count'] == 3
    assert result['records'][0]['restore_required'] is False


def test_restore_archived_script_moves_archive_back_to_source() -> None:
    original_repo_root = run_maintenance.REPO_ROOT
    original_maintenance_dir = run_maintenance.MAINTENANCE_DIR
    original_archive_root = run_maintenance.SCRIPT_ARCHIVE_ROOT
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / 'orchestrator'
            repo.mkdir()
            maintenance_dir = root / 'maintenance' / 'orchestrator-repo-maintenance'
            archive_root = maintenance_dir / 'archive' / 'scripts'
            archive = archive_root / '20260518T000000Z' / 'scripts__ready.py.abc'
            tombstone = Path(f'{archive}.tombstone.json')
            archive.parent.mkdir(parents=True)
            archive.write_text('print("restore")\n')
            digest = run_maintenance.file_sha256(archive)
            tombstone.write_text(json.dumps({
                'schema_version': 'orchestrator-script-archive-tombstone/v1',
                'source_path': 'scripts/ready.py',
                'archive_path': 'orchestrator-repo-maintenance/archive/scripts/20260518T000000Z/scripts__ready.py.abc',
                'source_sha256': digest,
            }) + '\n')
            run_maintenance.REPO_ROOT = repo.resolve()
            run_maintenance.MAINTENANCE_DIR = maintenance_dir.resolve()
            run_maintenance.SCRIPT_ARCHIVE_ROOT = archive_root.resolve()
            result = run_maintenance.restore_archived_script('orchestrator-repo-maintenance/archive/scripts/20260518T000000Z/scripts__ready.py.abc.tombstone.json')
            restored = repo / 'scripts' / 'ready.py'
            assert result['ok'] is True
            assert restored.exists()
            assert not archive.exists()
            assert run_maintenance.file_sha256(restored) == digest
    finally:
        run_maintenance.REPO_ROOT = original_repo_root
        run_maintenance.MAINTENANCE_DIR = original_maintenance_dir
        run_maintenance.SCRIPT_ARCHIVE_ROOT = original_archive_root



def test_restore_archived_script_missing_tombstone_fails_safely() -> None:
    result = run_maintenance.restore_archived_script('orchestrator-repo-maintenance/archive/scripts/missing.tombstone.json')
    assert result['ok'] is False
    assert result['reason'] == 'tombstone_missing_or_not_file'


def test_post_delete_verification_noop_is_ok() -> None:
    original_self_check = run_maintenance.run_maintenance_self_check
    try:
        run_maintenance.run_maintenance_self_check = lambda: {
            'returncode': 0,
            'payload': {'overall_status': 'ok', 'summary': {'ok': 12, 'warning': 0, 'error': 0}},
        }
        result = run_maintenance.build_post_delete_verification_result({
            'schema_version': 'orchestrator-script-delete-apply-result/v1',
            'deleted': [],
            'deleted_count': 0,
            'skipped_count': 1,
        })
    finally:
        run_maintenance.run_maintenance_self_check = original_self_check
    assert result['phase'] == 'G5'
    assert result['mutating'] is False
    assert result['ok'] is True
    assert result['deleted_count'] == 0
    assert any(item['name'] == 'no_deleted_records' and item['status'] == 'ok' for item in result['checks'])


def test_post_delete_verification_checks_absence_and_restore_failure() -> None:
    original_repo_root = run_maintenance.REPO_ROOT
    original_maintenance_dir = run_maintenance.MAINTENANCE_DIR
    original_archive_root = run_maintenance.SCRIPT_ARCHIVE_ROOT
    original_self_check = run_maintenance.run_maintenance_self_check
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / 'orchestrator'
            repo.mkdir()
            maintenance_dir = root / 'maintenance' / 'orchestrator-repo-maintenance'
            archive_root = maintenance_dir / 'archive' / 'scripts'
            archive_root.mkdir(parents=True)
            run_maintenance.REPO_ROOT = repo.resolve()
            run_maintenance.MAINTENANCE_DIR = maintenance_dir.resolve()
            run_maintenance.SCRIPT_ARCHIVE_ROOT = archive_root.resolve()
            run_maintenance.run_maintenance_self_check = lambda: {
                'returncode': 0,
                'payload': {'overall_status': 'ok', 'summary': {'ok': 12, 'warning': 0, 'error': 0}},
            }
            record = {
                'source_path': 'scripts/deleted.py',
                'archive_path': 'orchestrator-repo-maintenance/archive/scripts/20260518T000000Z/scripts__deleted.py.abc',
                'tombstone_path': 'orchestrator-repo-maintenance/archive/scripts/20260518T000000Z/scripts__deleted.py.abc.tombstone.json',
            }
            result = run_maintenance.build_post_delete_verification_result({
                'schema_version': 'orchestrator-script-delete-apply-result/v1',
                'deleted': [record],
                'deleted_count': 1,
                'skipped_count': 0,
            })
    finally:
        run_maintenance.REPO_ROOT = original_repo_root
        run_maintenance.MAINTENANCE_DIR = original_maintenance_dir
        run_maintenance.SCRIPT_ARCHIVE_ROOT = original_archive_root
        run_maintenance.run_maintenance_self_check = original_self_check
    assert result['ok'] is True
    statuses = {(item['name'], item['status']) for item in result['checks']}
    assert ('source_path_absent_after_delete', 'ok') in statuses
    assert ('archive_absent_after_delete', 'ok') in statuses
    assert ('tombstone_absent_after_delete', 'ok') in statuses
    assert ('restore_after_delete_fails_safely', 'ok') in statuses



def test_delete_readiness_empty_quarantine_is_report_only_noop() -> None:
    result = run_maintenance.build_delete_readiness_result({'records': []})
    assert result['phase'] == 'G1'
    assert result['mode'] == 'report_only'
    assert result['mutating'] is False
    assert result['archived_script_count'] == 0
    assert result['auto_delete_ready_count'] == 0


def test_delete_readiness_requires_clean_cycles_and_no_restore_flags() -> None:
    monitor = {
        'records': [
            {
                'source_path': 'scripts/ready.py',
                'archive_path': 'orchestrator-repo-maintenance/archive/scripts/ready.py',
                'tombstone_path': 'orchestrator-repo-maintenance/archive/scripts/ready.py.tombstone.json',
                'clean': True,
                'clean_cycle_count': 3,
                'restore_required': False,
                'restore_blocked': False,
                'blockers': [],
            },
            {
                'source_path': 'scripts/young.py',
                'archive_path': 'orchestrator-repo-maintenance/archive/scripts/young.py',
                'tombstone_path': 'orchestrator-repo-maintenance/archive/scripts/young.py.tombstone.json',
                'clean': True,
                'clean_cycle_count': 2,
                'restore_required': False,
                'restore_blocked': False,
                'blockers': [],
            },
            {
                'source_path': 'scripts/broken.py',
                'archive_path': 'orchestrator-repo-maintenance/archive/scripts/broken.py',
                'tombstone_path': 'orchestrator-repo-maintenance/archive/scripts/broken.py.tombstone.json',
                'clean': False,
                'clean_cycle_count': 0,
                'restore_required': True,
                'restore_blocked': False,
                'blockers': ['post_archive_smoke_failed'],
            },
        ]
    }
    result = run_maintenance.build_delete_readiness_result(monitor)
    by_path = {item['source_path']: item for item in result['records']}
    assert result['auto_delete_ready_count'] == 1
    assert by_path['scripts/ready.py']['planned_action'] == 'auto_delete_ready'
    assert by_path['scripts/young.py']['planned_action'] == 'archived_quarantine'
    assert 'insufficient_clean_quarantine_cycles' in by_path['scripts/young.py']['blockers']
    assert 'restore_required' in by_path['scripts/broken.py']['blockers']
    assert 'quarantine:post_archive_smoke_failed' in by_path['scripts/broken.py']['blockers']



def test_delete_dry_run_empty_readiness_is_non_mutating_noop() -> None:
    result = run_maintenance.build_delete_dry_run_result({'schema_version': 'orchestrator-script-delete-readiness/v1', 'records': []}, '2026-05-18T00:00:00Z')
    assert result['phase'] == 'G2'
    assert result['mode'] == 'monthly_dry_run_only'
    assert result['mutating'] is False
    assert result['evidence_period'] == '2026-05'
    assert result['operation_count'] == 0
    assert result['excluded_count'] == 0


def test_delete_dry_run_only_includes_auto_delete_ready_records() -> None:
    readiness = {
        'schema_version': 'orchestrator-script-delete-readiness/v1',
        'records': [
            {
                'source_path': 'scripts/ready.py',
                'archive_path': 'orchestrator-repo-maintenance/archive/scripts/ready.py',
                'tombstone_path': 'orchestrator-repo-maintenance/archive/scripts/ready.py.tombstone.json',
                'planned_action': 'auto_delete_ready',
                'delete_ready': True,
                'clean_cycle_count': 3,
                'required_clean_cycles': 3,
                'restore_command': 'python3 maintenance/orchestrator-repo-maintenance/run_maintenance.py --restore-archived-script tombstone',
                'blockers': [],
            },
            {
                'source_path': 'scripts/blocked.py',
                'archive_path': 'orchestrator-repo-maintenance/archive/scripts/blocked.py',
                'tombstone_path': 'orchestrator-repo-maintenance/archive/scripts/blocked.py.tombstone.json',
                'planned_action': 'archived_quarantine',
                'delete_ready': False,
                'blockers': ['insufficient_clean_quarantine_cycles'],
            },
        ],
    }
    result = run_maintenance.build_delete_dry_run_result(readiness, '2026-05-18T00:00:00Z')
    assert result['operation_count'] == 1
    assert result['excluded_count'] == 1
    assert result['operations'][0]['dry_run_action'] == 'would_delete_archived_script_and_tombstone'
    assert 'archive_hash_matches_tombstone' in result['operations'][0]['required_preflight']
    assert result['excluded'][0]['source_path'] == 'scripts/blocked.py'



def test_script_delete_apply_noops_when_no_ready_operations() -> None:
    result = run_maintenance.build_script_delete_apply_result({'operations': []}, apply=True)
    assert result['phase'] == 'G4'
    assert result['mutating'] is False
    assert result['ready_operation_count'] == 0
    assert result['deleted_count'] == 0
    assert result['skipped'][0]['reason'] == 'no_ready_delete_operations'


def test_script_delete_apply_deletes_one_validated_archive_and_tombstone() -> None:
    original_repo_root = run_maintenance.REPO_ROOT
    original_maintenance_dir = run_maintenance.MAINTENANCE_DIR
    original_archive_root = run_maintenance.SCRIPT_ARCHIVE_ROOT
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / 'orchestrator'
            repo.mkdir()
            maintenance_dir = root / 'maintenance' / 'orchestrator-repo-maintenance'
            archive_root = maintenance_dir / 'archive' / 'scripts'
            archive = archive_root / '20260518T000000Z' / 'scripts__ready.py.abc'
            tombstone = Path(f'{archive}.tombstone.json')
            archive.parent.mkdir(parents=True)
            archive.write_text('print("delete me")\n')
            digest = run_maintenance.file_sha256(archive)
            archive_rel = 'orchestrator-repo-maintenance/archive/scripts/20260518T000000Z/scripts__ready.py.abc'
            tombstone.write_text(json.dumps({
                'schema_version': 'orchestrator-script-archive-tombstone/v1',
                'source_path': 'scripts/ready.py',
                'archive_path': archive_rel,
                'source_sha256': digest,
            }) + '\n')
            run_maintenance.REPO_ROOT = repo.resolve()
            run_maintenance.MAINTENANCE_DIR = maintenance_dir.resolve()
            run_maintenance.SCRIPT_ARCHIVE_ROOT = archive_root.resolve()
            dry_run = {'operations': [{
                'source_path': 'scripts/ready.py',
                'archive_path': archive_rel,
                'tombstone_path': f'{archive_rel}.tombstone.json',
                'required_preflight': ['archive_hash_matches_tombstone'],
            }]}
            result = run_maintenance.build_script_delete_apply_result(dry_run, apply=True)
            assert result['mutating'] is True
            assert result['deleted_count'] == 1
            assert result['skipped_count'] == 0
            assert not archive.exists()
            assert not tombstone.exists()
            assert not (repo / 'scripts' / 'ready.py').exists()
            assert result['deleted'][0]['source_sha256'] == digest
    finally:
        run_maintenance.REPO_ROOT = original_repo_root
        run_maintenance.MAINTENANCE_DIR = original_maintenance_dir
        run_maintenance.SCRIPT_ARCHIVE_ROOT = original_archive_root



def test_script_auto_archive_apply_validates_empty_dry_run_with_smoke_and_monitor() -> None:
    dry_run = {
        'schema_version': 'orchestrator-script-archive-dry-run/v1',
        'mutating': False,
        'proposals': [],
    }
    promotion = {
        'schema_version': 'script-auto-archive-promotion/v1',
        'eligible_paths': [],
    }
    smoke = {'schema_version': 'orchestrator-post-archive-smoke/v1', 'ok': True, 'checks': []}
    monitor = {'schema_version': 'orchestrator-script-quarantine-monitor/v1', 'ok': True, 'archived_script_count': 0, 'restore_required_count': 0}
    result = run_scheduled_maintenance.build_script_auto_archive_apply_result(dry_run, promotion, post_archive_smoke=smoke, quarantine_monitor=monitor)
    assert result['phase'] == 'H2'
    assert result['mode'] == 'script-auto-archive-apply'
    assert result['ok'] is True
    assert result['status'] == 'no_op'
    assert result['archive_dry_run_proposal_count'] == 0



def test_script_auto_archive_apply_requires_promotion_evidence_for_proposals() -> None:
    dry_run = {
        'schema_version': 'orchestrator-script-archive-dry-run/v1',
        'mutating': False,
        'proposals': [
            {
                'source_path': 'scripts/ready.py',
                'archive_path': 'orchestrator-repo-maintenance/archive/scripts/ready.py',
                'tombstone_path': 'orchestrator-repo-maintenance/archive/scripts/ready.py.tombstone.json',
                'source_sha256': 'abc',
                'restore_command': 'python3 maintenance/orchestrator-repo-maintenance/run_maintenance.py --restore-archived-script tombstone',
            }
        ],
    }
    promotion = {'schema_version': 'script-auto-archive-promotion/v1', 'eligible_paths': []}
    result = run_scheduled_maintenance.build_script_auto_archive_apply_result(dry_run, promotion)
    assert result['ok'] is False
    assert result['blocked_reason'] == 'fresh_archive_evidence_validation_failed'



def test_script_auto_delete_apply_validates_current_month_empty_dry_run() -> None:
    dry_run = {
        'schema_version': 'orchestrator-script-delete-dry-run/v1',
        'mutating': False,
        'evidence_period': '2026-05',
        'operations': [],
    }
    now = run_scheduled_maintenance.datetime.fromisoformat('2026-05-18T23:12:00+00:00')
    post_delete = {
        'schema_version': 'orchestrator-script-post-delete-verification/v1',
        'mode': 'post_delete_verification',
        'ok': True,
        'deleted_count': 0,
        'check_count': 3,
    }
    result = run_scheduled_maintenance.build_script_auto_delete_apply_result(dry_run, now, post_delete_verification=post_delete)
    assert result['phase'] == 'G6'
    assert result['mode'] == 'script-auto-delete-apply'
    assert result['mutating'] is False
    assert result['ok'] is True
    assert result['status'] == 'no_op'
    assert result['delete_dry_run_operation_count'] == 0
    assert result['fresh_evidence_validation']['ok'] is True
    assert result['delegated_apply']['implemented'] is True
    assert result['post_delete_verification']['implemented'] is True
    assert result['post_delete_verification']['ok'] is True


def test_script_auto_delete_apply_blocks_stale_or_nonempty_dry_run() -> None:
    stale = {
        'schema_version': 'orchestrator-script-delete-dry-run/v1',
        'mutating': False,
        'evidence_period': '2026-04',
        'operations': [],
    }
    now = run_scheduled_maintenance.datetime.fromisoformat('2026-05-18T23:12:00+00:00')
    stale_result = run_scheduled_maintenance.build_script_auto_delete_apply_result(stale, now)
    assert stale_result['ok'] is False
    assert stale_result['blocked_reason'] == 'fresh_evidence_validation_failed'

    nonempty = {
        'schema_version': 'orchestrator-script-delete-dry-run/v1',
        'mutating': False,
        'evidence_period': '2026-05',
        'operations': [
            {
                'source_path': 'scripts/ready.py',
                'archive_path': 'orchestrator-repo-maintenance/archive/scripts/ready.py',
                'tombstone_path': 'orchestrator-repo-maintenance/archive/scripts/ready.py.tombstone.json',
                'required_preflight': ['fresh_delete_readiness_report'],
            }
        ],
    }
    post_delete = {
        'schema_version': 'orchestrator-script-post-delete-verification/v1',
        'mode': 'post_delete_verification',
        'ok': True,
        'deleted_count': 0,
        'check_count': 3,
    }
    nonempty_result = run_scheduled_maintenance.build_script_auto_delete_apply_result(nonempty, now, {
        'schema_version': 'orchestrator-script-delete-apply-result/v1',
        'deleted_count': 0,
        'skipped_count': 1,
        'mutating': False,
    }, post_delete)
    assert nonempty_result['ok'] is False
    assert nonempty_result['blocked_reason'] == 'delete_apply_preflight_blocked'
    assert nonempty_result['delete_dry_run_operation_count'] == 1



def test_script_auto_delete_apply_requires_post_delete_verification() -> None:
    dry_run = {
        'schema_version': 'orchestrator-script-delete-dry-run/v1',
        'mutating': False,
        'evidence_period': '2026-05',
        'operations': [],
    }
    now = run_scheduled_maintenance.datetime.fromisoformat('2026-05-18T23:12:00+00:00')
    missing = run_scheduled_maintenance.build_script_auto_delete_apply_result(dry_run, now)
    assert missing['ok'] is False
    assert missing['blocked_reason'] == 'post_delete_verification_failed'

    failed = run_scheduled_maintenance.build_script_auto_delete_apply_result(dry_run, now, post_delete_verification={
        'schema_version': 'orchestrator-script-post-delete-verification/v1',
        'ok': False,
    })
    assert failed['ok'] is False
    assert failed['blocked_reason'] == 'post_delete_verification_failed'



def main() -> int:
    tests = [
        test_preflight_missing_path,
        test_invalid_json_classified,
        test_envelope_schema_and_retry,
        test_context_apply_dry_run_does_not_edit,
        test_script_usage_self_check_validates_complete_fresh_join,
        test_script_usage_self_check_rejects_incomplete_join,
        test_maintenance_self_check_expects_script_cleanup_crons,
        test_maintenance_self_check_expects_pressure_check_cron,
        test_maintenance_self_check_accepts_script_auto_archive_and_delete_cron_inventory,
        test_maintenance_self_check_rejects_missing_pressure_check_cron_inventory,
        test_objective_status_classifies_met_partial_degraded_and_no_action,
        test_objective_rollup_preserves_next_action_as_status_not_execution,
        test_self_check_objective_rollup_marks_missing_scheduler,
        test_cleanup_plan_uses_usage_aware_action_classes,
        test_cleanup_plan_blocks_approved_candidates_with_usage_blockers,
        test_cleanup_plan_reports_gate_ready_and_blockers,
        test_cleanup_plan_autonomously_promotes_archive_when_deterministic_evidence_is_clear,
        test_cleanup_plan_blocks_missing_usage_summary_rows,
        test_cleanup_candidate_history_tracks_repeated_no_use_state,
        test_cleanup_candidate_history_marks_mature_after_window_and_observations,
        test_cleanup_candidate_history_resets_no_use_on_observed_usage,
        test_scheduled_cleanup_delete_readiness_guard_blocks_delete_ready,
        test_scheduled_cleanup_delete_readiness_guard_allows_current_zero_delete_ready,
        test_scheduled_confidence_stage_accepts_usage_aware_ready_actions,
        test_cleanup_evidence_diff_suppresses_counter_only_noise,
        test_cleanup_evidence_diff_reports_action_and_maturity_changes,
        test_script_cleanup_blocker_report_assigns_autonomous_next_actions,
        test_script_cleanup_evidence_movement_reports_autonomous_progress,
        test_scheduled_script_evidence_refresh_blocks_only_unowned_actions,
        test_clutter_apply_dry_run_includes_only_trivial_untracked_clutter,
        test_clutter_apply_dry_run_excludes_runtime_and_unknown_clutter,
        test_git_status_confirms_only_untracked_or_ignored_exact_path,
        test_build_ds_store_apply_result_skips_non_e2_operations,
        test_git_status_confirms_untracked_or_ignored_tree_entries,
        test_build_pycache_apply_result_requires_no_live_python_process,
        test_generated_run_retention_keeps_latest_and_selects_oldest,
        test_generated_artifact_retention_result_protects_status_outputs,
        test_post_apply_verification_passes_with_self_check_and_repo_health,
        test_post_apply_verification_fails_on_self_check_error,
        test_archive_layout_contract_defines_tombstone_and_restore,
        test_archive_relative_path_is_stable_and_path_safe,
        test_archive_dry_run_only_proposes_fully_gated_candidates,
        test_archive_dry_run_blocks_ready_candidate_when_source_missing,
        test_script_archive_apply_noops_when_no_ready_proposals,
        test_script_archive_apply_moves_one_candidate_and_writes_tombstone,
        test_post_archive_smoke_passes_no_archived_paths_with_refreshed_outputs,
        test_archived_touched_surface_checks_validate_tombstone_hash,
        test_quarantine_monitor_empty_archive_is_clean_noop,
        test_quarantine_monitor_tracks_clean_cycle_for_archived_script,
        test_restore_archived_script_moves_archive_back_to_source,
        test_restore_archived_script_missing_tombstone_fails_safely,
        test_post_delete_verification_noop_is_ok,
        test_post_delete_verification_checks_absence_and_restore_failure,
        test_delete_readiness_empty_quarantine_is_report_only_noop,
        test_delete_readiness_requires_clean_cycles_and_no_restore_flags,
        test_delete_dry_run_empty_readiness_is_non_mutating_noop,
        test_delete_dry_run_only_includes_auto_delete_ready_records,
        test_script_delete_apply_noops_when_no_ready_operations,
        test_script_delete_apply_deletes_one_validated_archive_and_tombstone,
        test_script_auto_archive_apply_validates_empty_dry_run_with_smoke_and_monitor,
        test_script_auto_archive_apply_requires_promotion_evidence_for_proposals,
        test_script_auto_delete_apply_validates_current_month_empty_dry_run,
        test_script_auto_delete_apply_blocks_stale_or_nonempty_dry_run,
        test_script_auto_delete_apply_requires_post_delete_verification,
    ]
    failures = []
    for test in tests:
        try:
            test()
            print(f'OK {test.__name__}')
        except Exception as exc:
            failures.append((test.__name__, exc))
            print(f'FAIL {test.__name__}: {type(exc).__name__}: {exc}')
    if failures:
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
