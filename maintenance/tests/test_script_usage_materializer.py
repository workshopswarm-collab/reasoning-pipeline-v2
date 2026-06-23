#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

MAINTENANCE_ROOT = Path(__file__).resolve().parents[1]
MATERIALIZER_PATH = MAINTENANCE_ROOT / 'orchestrator-repo-maintenance' / 'script_usage_materializer.py'
GENERATED_ROOT = MAINTENANCE_ROOT / 'orchestrator-repo-maintenance' / 'generated'
C1_SUMMARY_PATH = GENERATED_ROOT / 'script-usage-ledger-c1-summary.json'
C1_EVIDENCE_PATH = GENERATED_ROOT / 'script-invocation-ledger' / 'script-usage-materializer-c1-ledger-parser-2026-05-17.json'
SCRIPT_USAGE_SUMMARY_PATH = GENERATED_ROOT / 'script-usage-summary.json'
C2_EVIDENCE_PATH = GENERATED_ROOT / 'script-invocation-ledger' / 'script-usage-materializer-c2-classifier-join-2026-05-17.json'
C3_EVIDENCE_PATH = GENERATED_ROOT / 'script-invocation-ledger' / 'script-usage-materializer-c3-inventory-cross-check-2026-05-17.json'
C4_EVIDENCE_PATH = GENERATED_ROOT / 'script-invocation-ledger' / 'script-usage-materializer-c4-scheduler-docs-logs-2026-05-18.json'

spec = importlib.util.spec_from_file_location('script_usage_materializer_for_tests', MATERIALIZER_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError(f'could not import {MATERIALIZER_PATH}')
script_usage_materializer = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = script_usage_materializer
spec.loader.exec_module(script_usage_materializer)


def ledger_row(**overrides: Any) -> dict[str, Any]:
    row = {
        'schema_version': 'script-invocation/v1',
        'event': 'start',
        'run_id': 'script-20260517T120000Z-test',
        'ts': '2026-05-17T12:00:00Z',
        'script': 'scripts/example.py',
        'argv_sanitized': ['--help'],
        'trigger': 'manual',
    }
    row.update(overrides)
    return row


def write_jsonl(path: Path, rows: list[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rendered: list[str] = []
    for row in rows:
        if isinstance(row, str):
            rendered.append(row)
        else:
            rendered.append(json.dumps(row, sort_keys=True))
    path.write_text('\n'.join(rendered) + '\n')


def test_c1_parser_tolerates_malformed_rows_and_summarizes_counts() -> None:
    with tempfile.TemporaryDirectory(prefix='openclaw-usage-materializer-') as tmpdir:
        ledger_dir = Path(tmpdir) / 'ledger'
        write_jsonl(
            ledger_dir / '2026-05-17.jsonl',
            [
                ledger_row(event='start', run_id='run-ok', ts='2026-05-17T12:00:00Z', script='scripts/a.py', trigger='launchd'),
                ledger_row(event='finish', run_id='run-ok', ts='2026-05-17T12:00:02Z', script='scripts/a.py', trigger='launchd', status='completed', exit_code=0),
                '{not json',
                ['not', 'object'],
                ledger_row(event='finish', run_id='run-fail', ts='2026-05-17T12:01:00Z', script='scripts/b.py', status='exception', exit_code=None, parent_script='scripts/parent.py'),
                ledger_row(event='finish', run_id='run-bad-schema', schema_version='wrong', script='scripts/c.py'),
                ledger_row(event='finish', run_id='run-missing-script', script=''),
            ],
        )

        payload = script_usage_materializer.build_summary(ledger_dir)

    assert payload['schema_version'] == 'openclaw-script-usage-ledger-parser/v1'
    assert payload['phase'] == 'C1'
    assert payload['parser_scope'] == 'ledger_jsonl_only_no_classifier_join'
    summary = payload['summary']
    assert summary['shard_count'] == 1
    assert summary['total_lines'] == 7
    assert summary['parsed_event_count'] == 3
    assert summary['parse_issue_count'] == 4
    assert summary['script_count'] == 2
    assert summary['start_count'] == 1
    assert summary['finish_count'] == 2
    assert summary['success_count'] == 1
    assert summary['failure_count'] == 1
    issue_kinds = {issue['kind'] for issue in payload['issues']}
    assert issue_kinds == {'malformed_json', 'non_object_row', 'unexpected_schema', 'missing_script'}
    scripts = {item['script']: item for item in payload['scripts']}
    assert scripts['scripts/a.py']['trigger_counts'] == {'launchd': 2}
    assert scripts['scripts/a.py']['last_success_at'] == '2026-05-17T12:00:02Z'
    assert scripts['scripts/b.py']['failure_count'] == 1
    assert scripts['scripts/b.py']['parent_callers'] == ['scripts/parent.py']


def test_c1_cli_writes_json_and_markdown_outputs() -> None:
    with tempfile.TemporaryDirectory(prefix='openclaw-usage-materializer-cli-') as tmpdir:
        tmp = Path(tmpdir)
        ledger_dir = tmp / 'ledger'
        output_json = tmp / 'summary.json'
        output_md = tmp / 'summary.md'
        write_jsonl(
            ledger_dir / '2026-05-18.jsonl',
            [
                ledger_row(event='start', run_id='run-cli', ts='2026-05-18T00:00:00Z', script='scripts/cli.py'),
                ledger_row(event='finish', run_id='run-cli', ts='2026-05-18T00:00:01Z', script='scripts/cli.py', status='system_exit', exit_code=0),
            ],
        )
        payload = script_usage_materializer.build_summary(ledger_dir)
        script_usage_materializer.write_outputs(payload, output_json, output_md)

        written = json.loads(output_json.read_text())
        markdown = output_md.read_text()

    assert written['summary']['success_count'] == 1
    assert '`scripts/cli.py`' in markdown
    assert 'Success / failure: 1 / 0' in markdown


def test_c4_classifier_join_marks_missing_usage_and_reviews_inventory_scope() -> None:
    with tempfile.TemporaryDirectory(prefix='openclaw-usage-materializer-c4-', dir='/private/tmp') as tmpdir:
        tmp = Path(tmpdir)
        ledger_dir = tmp / 'ledger'
        classification_json = tmp / 'script-classification.json'
        (tmp / 'scripts').mkdir()
        (tmp / 'scripts' / 'observed.py').write_text('print("observed")\n')
        (tmp / 'scripts' / 'unclassified.py').write_text('print("unclassified")\n')
        (tmp / 'loose').mkdir()
        (tmp / 'loose' / 'tool.py').write_text('print("outside")\n')
        cron_json = tmp / 'cron' / 'jobs.json'
        cron_json.parent.mkdir()
        cron_json.write_text(json.dumps({'version': 1, 'jobs': [{'name': 'Run missing', 'payload': {'message': 'python3 scripts/missing.py --safe'}}]}))
        launchd_root = tmp / 'launchd'
        launchd_root.mkdir()
        (launchd_root / 'example.plist').write_text('<plist><string>scripts/observed.py</string></plist>')
        docs_root = tmp / 'docs'
        docs_root.mkdir()
        (docs_root / 'runbook.md').write_text('Operator runbook mentions scripts/missing.py for diagnostics.\n')
        logs_root = tmp / 'logs'
        logs_root.mkdir()
        (logs_root / 'runtime.log').write_text('completed scripts/missing.py from scheduler\n')
        write_jsonl(
            ledger_dir / '2026-05-19.jsonl',
            [
                ledger_row(event='start', run_id='run-observed', ts='2026-05-19T00:00:00Z', script='scripts/observed.py', trigger='launchd'),
                ledger_row(event='finish', run_id='run-observed', ts='2026-05-19T00:00:02Z', script='scripts/observed.py', trigger='launchd', status='completed', exit_code=0),
                ledger_row(event='start', run_id='run-unmatched', ts='2026-05-19T00:01:00Z', script='scripts/unmatched.py'),
                ledger_row(event='start', run_id='run-external', ts='2026-05-19T00:02:00Z', script='ps', trigger='subprocess/status', parent_script='scripts/parent.py'),
            ],
        )
        classification_json.write_text(json.dumps({
            'schema_version': 'test/v1',
            'records': [
                {'path': 'scripts/observed.py', 'name': 'observed.py', 'classification': 'active_entrypoint', 'confidence': 'high', 'inbound_reference_count': 2},
                {'path': 'scripts/missing.py', 'name': 'missing.py', 'classification': 'manual_repair', 'confidence': 'medium', 'inbound_reference_count': 0},
            ],
        }))

        original = script_usage_materializer.build_reference_evidence
        script_usage_materializer.build_reference_evidence = lambda records: original(
            records,
            cron_json=cron_json,
            launchd_root=launchd_root,
            doc_roots=[docs_root],
            runtime_log_roots=[logs_root],
        )
        try:
            payload = script_usage_materializer.build_joined_summary(ledger_dir, classification_json, tmp, [tmp / 'scripts'])
        finally:
            script_usage_materializer.build_reference_evidence = original

    assert payload['schema_version'] == 'openclaw-script-usage-summary/v1'
    assert payload['phase'] == 'C4'
    assert payload['parser_scope'] == 'ledger_jsonl_with_classifier_join_inventory_scheduler_docs_logs'
    assert payload['coverage_default_for_missing_usage'] == 'pre_instrumentation_unknown'
    assert payload['summary']['classified_script_count'] == 2
    assert payload['summary']['observed_classified_script_count'] == 1
    assert payload['summary']['parent_observed_script_count'] == 1
    assert payload['summary']['pre_instrumentation_unknown_count'] == 0
    assert payload['summary']['unmatched_ledger_script_count'] == 1
    assert payload['summary']['external_ledger_command_count'] == 1
    assert payload['summary']['outside_approved_roots_count'] == 1
    assert payload['summary']['unclassified_approved_scope_count'] == 1
    assert payload['summary']['classified_missing_from_filesystem_count'] == 1
    scripts = {item['path']: item for item in payload['scripts']}
    assert scripts['scripts/observed.py']['coverage_status'] == 'direct'
    assert scripts['scripts/observed.py']['instrumented'] is True
    assert scripts['scripts/observed.py']['filesystem_present'] is True
    assert scripts['scripts/observed.py']['inventory_scope'] == 'approved_root'
    assert scripts['scripts/observed.py']['run_count_total'] == 1
    assert scripts['scripts/observed.py']['trigger_counts'] == {'launchd': 2}
    assert 'ledger' in scripts['scripts/observed.py']['evidence_sources']
    assert scripts['scripts/observed.py']['evidence_refresh_action']['owner_lane'] == 'Maintenance: Orchestrator Script Evidence Refresh'
    assert scripts['scripts/observed.py']['evidence_refresh_action']['autonomous'] is True
    assert scripts['scripts/observed.py']['evidence_refresh_action']['action'] == 'retain_observed_script'
    assert scripts['scripts/missing.py']['coverage_status'] == 'parent_observed'
    assert scripts['scripts/missing.py']['instrumented'] is False
    assert scripts['scripts/missing.py']['filesystem_present'] is False
    assert scripts['scripts/missing.py']['inventory_scope'] == 'missing_from_filesystem'
    assert 'pre_instrumentation_unknown' not in scripts['scripts/missing.py']['cleanup_eligibility_blockers']
    assert 'has_cron_reference' in scripts['scripts/missing.py']['cleanup_eligibility_blockers']
    assert 'has_operator_doc_reference' in scripts['scripts/missing.py']['cleanup_eligibility_blockers']
    assert 'has_runtime_log_reference' in scripts['scripts/missing.py']['cleanup_eligibility_blockers']
    assert {'cron', 'operator_docs', 'runtime_logs'} <= set(scripts['scripts/missing.py']['evidence_sources'])
    assert scripts['scripts/missing.py']['evidence_refresh_action']['action'] == 'continue_observation_until_mature'
    assert scripts['scripts/missing.py']['evidence_refresh_action']['autonomous'] is True
    assert payload['unmatched_ledger_scripts'][0]['script'] == 'scripts/unmatched.py'
    assert payload['external_ledger_commands'][0]['script'] == 'ps'
    assert payload['inventory_scope_review']['outside_approved_roots'][0]['path'] == 'loose/tool.py'
    assert payload['inventory_scope_review']['unclassified_approved_scope'][0]['path'] == 'scripts/unclassified.py'


def test_c1_generated_artifacts_are_parseable_and_scope_limited() -> None:
    summary = json.loads(C1_SUMMARY_PATH.read_text())
    evidence = json.loads(C1_EVIDENCE_PATH.read_text())

    assert summary['schema_version'] == 'openclaw-script-usage-ledger-parser/v1'
    assert summary['phase'] == 'C1'
    assert summary['parser_scope'] == 'ledger_jsonl_only_no_classifier_join'
    assert 'summary' in summary
    assert 'scripts' in summary
    assert evidence['schema_version'] == 'openclaw-script-usage-materializer-c1-evidence/v1'
    assert evidence['phase'] == 'C1'
    assert evidence['implemented_script'] == 'maintenance/orchestrator-repo-maintenance/script_usage_materializer.py'
    assert 'classifier join' in evidence['cross_reference']['not_yet_in_scope']
    assert evidence['live_summary_artifacts']['json'] == C1_SUMMARY_PATH.relative_to(MAINTENANCE_ROOT.parent).as_posix()


def test_c4_generated_artifacts_are_parseable_and_include_inventory_scope_review() -> None:
    summary = json.loads(SCRIPT_USAGE_SUMMARY_PATH.read_text())
    evidence = json.loads(C4_EVIDENCE_PATH.read_text())

    assert summary['schema_version'] == 'openclaw-script-usage-summary/v1'
    assert summary['phase'] == 'C4'
    assert summary['coverage_default_for_missing_usage'] == 'pre_instrumentation_unknown'
    assert summary['summary']['classified_script_count'] == len(summary['scripts'])
    assert summary['summary']['pre_instrumentation_unknown_count'] > 0
    assert 'inventory_scope_review' in summary
    assert 'reference_evidence_summary' in summary
    assert 'outside_approved_roots' in summary['inventory_scope_review']
    assert evidence['schema_version'] == 'openclaw-script-usage-materializer-c4-evidence/v1'
    assert evidence['phase'] == 'C4'
    assert evidence['live_summary_artifacts']['json'] == SCRIPT_USAGE_SUMMARY_PATH.relative_to(MAINTENANCE_ROOT.parent).as_posix()


def main() -> int:
    tests = [
        test_c1_parser_tolerates_malformed_rows_and_summarizes_counts,
        test_c1_cli_writes_json_and_markdown_outputs,
        test_c4_classifier_join_marks_missing_usage_and_reviews_inventory_scope,
        test_c1_generated_artifacts_are_parseable_and_scope_limited,
        test_c4_generated_artifacts_are_parseable_and_include_inventory_scope_review,
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
