import io
from hashlib import sha256
import json
import math
import os
import stat
from dataclasses import FrozenInstanceError, asdict, replace
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from benchmarks import paired_codex
from benchmarks.model_routing import ModelSettings, RoutingConfig
from runtime import tree as runtime_tree
from runtime.providers import ProviderCapability, ProviderResult


OBSERVED_JSONL = "\n".join((
    json.dumps({"type": "thread.started", "thread_id": "redacted"}),
    json.dumps({"type": "turn.started"}),
    json.dumps({"type": "item.completed", "item": {
        "id": "redacted", "type": "agent_message", "text": "REDACTED"
    }}),
    json.dumps({"type": "turn.completed", "usage": {
        "input_tokens": 20,
        "cached_input_tokens": 4,
        "cache_write_input_tokens": 0,
        "output_tokens": 5,
        "reasoning_output_tokens": 1,
    }}),
))


def fake_run_contract():
    return paired_codex.RunContract(
        benchmark_version="codex-readonly-v1",
        scorer_version="finding-overlap-v1",
        cli_version="codex-cli 0.147.0",
        adapter_fingerprint="a" * 64,
        routing_config_hash="b" * 64,
        timeout_seconds=120,
        sandbox="read-only",
        acceptance_contract_hash="c" * 64,
    )


def fake_case_snapshots():
    return tuple(
        paired_codex.CaseSnapshot(
            case_id,
            baseline=str(index) * 40,
            subject_tree_hash=str(index + 3) * 40,
            case_definition_hash=str(index + 6) * 64,
        )
        for index, case_id in enumerate(("small", "medium", "complex"), 1)
    )


def fake_case_definitions():
    return tuple(
        paired_codex.load_case_definition(paired_codex.CASE_ROOT / case_id)
        for case_id in ("small", "medium", "complex")
    )


def fake_routing_config():
    return RoutingConfig(
        strategy="weighted_complexity_size",
        complexity_weight=0.6,
        size_weight=0.4,
        worker_max_score=0.33,
        expert_max_score=0.66,
        models={
            "worker": ModelSettings("gpt-5.6-luna", "medium"),
            "expert": ModelSettings("gpt-5.6-terra", "high"),
            "lead": ModelSettings("gpt-5.6-sol", "high"),
            "reviewer": ModelSettings("gpt-5.6-terra", "high"),
        },
    )


def fake_schedule(seed=41):
    return paired_codex.build_schedule(
        seed,
        fake_run_contract(),
        fake_case_snapshots(),
        fake_case_definitions(),
        fake_routing_config(),
    )


def fake_execution_plan(case, arm):
    return paired_codex.build_arm_execution_plan(case, arm, fake_routing_config())


def completed_result(findings, *, marker=""):
    final = json.dumps({"findings": findings}, separators=(",", ":")) + marker
    output = "\n".join((
        json.dumps({"type": "thread.started", "thread_id": "RAW_THREAD_SENTINEL"}),
        json.dumps({"type": "turn.started"}),
        json.dumps({"type": "item.completed", "item": {
            "id": "redacted", "type": "agent_message", "text": final,
        }}),
        json.dumps({"type": "turn.completed", "usage": {
            "input_tokens": 100,
            "cached_input_tokens": 0,
            "cache_write_input_tokens": 0,
            "output_tokens": 20,
            "reasoning_output_tokens": 5,
        }}),
    ))
    return ProviderResult("completed", "codex", "codex", False, 0, output, None, {})


def fake_capability(_provider, *, probe_version=False):
    return ProviderCapability("codex", True, "/fake/codex", "codex-cli 0.147.0")


def real_case_snapshot(case):
    with tempfile.TemporaryDirectory() as directory:
        _, baseline, tree_hash = paired_codex.copy_case_repo(case, Path(directory))
    return paired_codex.CaseSnapshot(
        case.case_id,
        baseline,
        tree_hash,
        paired_codex.canonical_case_definition_hash(case),
    )


def complete_arm_record(schedule):
    entry = schedule.entries[0]
    snapshot = next(case for case in schedule.cases if case.case_id == entry.case_id)
    plan = next(
        plan for plan in schedule.execution_plans
        if (plan.case_id, plan.arm) == (entry.case_id, entry.arm)
    )
    planned = plan.invocations[0]
    invocation = paired_codex.InvocationRecord(
        node_id=planned.node_id,
        requested_provider="codex",
        provider="codex",
        fallback_used=False,
        exit_code=0,
        requested_model=planned.requested_model,
        requested_reasoning_effort=planned.requested_reasoning_effort,
        actual_model=planned.requested_model,
        status="completed",
        receipt=f"receipts/{entry.position:03d}-{entry.case_id}-{entry.arm}/lead.jsonl",
        output_hash="d" * 64,
        input_tokens=100,
        cached_input_tokens=0,
        cache_write_input_tokens=0,
        output_tokens=20,
        reasoning_output_tokens=5,
        total_tokens=120,
        incomplete_reasons=(),
    )
    contract = schedule.run_contract
    return paired_codex.ArmRecord(
        entry=entry,
        seed=schedule.seed,
        benchmark_version=contract.benchmark_version,
        scorer_version=contract.scorer_version,
        baseline=snapshot.baseline,
        subject_tree_hash=snapshot.subject_tree_hash,
        case_definition_hash=snapshot.case_definition_hash,
        routing_config_hash=contract.routing_config_hash,
        cli_version=contract.cli_version,
        adapter_fingerprint=contract.adapter_fingerprint,
        timeout_seconds=contract.timeout_seconds,
        sandbox=contract.sandbox,
        acceptance_contract_hash=contract.acceptance_contract_hash,
        wall_seconds=1.25,
        invocations=(invocation,),
        score=paired_codex.Score(1, 0, 0, 1.0, 1.0, 1.0, True),
        planned_nodes=1,
        executed_nodes=1,
        failed_nodes=0,
        pruned_nodes=0,
        critical_path_nodes=1,
        completion_state="complete",
        incomplete_reasons=(),
    )


def complete_canopy_record(schedule):
    base = complete_arm_record(schedule)
    entry = next(
        entry for entry in schedule.entries
        if entry.case_id == "small" and entry.repetition == 1 and entry.arm == "canopy"
    )
    slug = f"{entry.position:03d}-{entry.case_id}-{entry.arm}"
    plan = next(
        plan for plan in schedule.execution_plans
        if (plan.case_id, plan.arm) == (entry.case_id, entry.arm)
    )
    planned_leaf, planned_reviewer = plan.invocations
    leaf = replace(
        base.invocations[0],
        node_id=planned_leaf.node_id,
        requested_model=planned_leaf.requested_model,
        requested_reasoning_effort=planned_leaf.requested_reasoning_effort,
        actual_model=planned_leaf.requested_model,
        receipt=f"receipts/{slug}/{planned_leaf.node_id}.jsonl",
    )
    reviewer = replace(
        base.invocations[0],
        node_id=planned_reviewer.node_id,
        requested_model=planned_reviewer.requested_model,
        requested_reasoning_effort=planned_reviewer.requested_reasoning_effort,
        actual_model=planned_reviewer.requested_model,
        receipt=f"receipts/{slug}/{planned_reviewer.node_id}.jsonl",
        output_hash="e" * 64,
    )
    return replace(
        base,
        entry=entry,
        invocations=(leaf, reviewer),
        planned_nodes=2,
        executed_nodes=2,
        critical_path_nodes=2,
    )


def write_complete_records_and_receipts_for_test(seed=41):
    schedule = fake_schedule(seed)
    directory = tempfile.TemporaryDirectory()
    state_root = Path(directory.name)
    records = []
    for entry in schedule.entries:
        snapshot = next(case for case in schedule.cases if case.case_id == entry.case_id)
        plan = next(
            plan for plan in schedule.execution_plans
            if (plan.case_id, plan.arm) == (entry.case_id, entry.arm)
        )
        invocations = []
        slug = f"{entry.position:03d}-{entry.case_id}-{entry.arm}"
        for index, planned in enumerate(plan.invocations):
            output_hash = sha256(f"{entry.position}:{planned.node_id}".encode()).hexdigest()
            receipt = f"receipts/{slug}/{planned.node_id}.jsonl"
            path = state_root / receipt
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"output_hash": output_hash}) + "\n", encoding="utf-8")
            path.chmod(0o600)
            total_tokens = (100 if entry.arm == "sequential" else 120) if index == len(plan.invocations) - 1 else 0
            invocations.append(paired_codex.InvocationRecord(
                node_id=planned.node_id,
                requested_provider="codex",
                provider="codex",
                fallback_used=False,
                exit_code=0,
                requested_model=planned.requested_model,
                requested_reasoning_effort=planned.requested_reasoning_effort,
                actual_model=planned.requested_model,
                status="completed",
                receipt=receipt,
                output_hash=output_hash,
                input_tokens=total_tokens,
                cached_input_tokens=0,
                cache_write_input_tokens=0,
                output_tokens=0,
                reasoning_output_tokens=0,
                total_tokens=total_tokens,
                incomplete_reasons=(),
            ))
        score = (
            paired_codex.Score(1, 1, 1, 0.5, 0.5, 0.5, False)
            if entry.arm == "sequential"
            else paired_codex.Score(9, 1, 1, 0.9, 0.9, 0.9, True)
        )
        contract = schedule.run_contract
        records.append(paired_codex.ArmRecord(
            entry=entry,
            seed=seed,
            benchmark_version=contract.benchmark_version,
            scorer_version=contract.scorer_version,
            baseline=snapshot.baseline,
            subject_tree_hash=snapshot.subject_tree_hash,
            case_definition_hash=snapshot.case_definition_hash,
            routing_config_hash=contract.routing_config_hash,
            cli_version=contract.cli_version,
            adapter_fingerprint=contract.adapter_fingerprint,
            timeout_seconds=contract.timeout_seconds,
            sandbox=contract.sandbox,
            acceptance_contract_hash=contract.acceptance_contract_hash,
            wall_seconds=10.0 if entry.arm == "sequential" else 12.0,
            invocations=tuple(invocations),
            score=score,
            planned_nodes=len(plan.invocations),
            executed_nodes=len(plan.invocations),
            failed_nodes=0,
            pruned_nodes=0,
            critical_path_nodes=1 if entry.arm == "sequential" else 2,
            completion_state="complete",
            incomplete_reasons=(),
        ))
    return schedule, tuple(records), state_root, directory


class PairedCodexTests(unittest.TestCase):
    def test_all_nine_complete_pairs_are_required_for_publication(self):
        schedule, records, state_root, cleanup = write_complete_records_and_receipts_for_test()
        self.addCleanup(cleanup.cleanup)
        report = paired_codex.calculate_report(schedule, records, state_root=state_root)
        self.assertTrue(report.publishable)
        self.assertEqual((9, 18), (len(report.pairs), report.sample_count))
        self.assertEqual((20.0, 20.0, 0.4), (
            report.median_token_delta_percent,
            report.median_time_delta_percent,
            report.median_quality_delta,
        ))
        self.assertEqual((0.0, 1.0), (
            report.sequential_pass_rate, report.canopy_pass_rate
        ))
        blocked = paired_codex.calculate_report(
            schedule, records[:-1], state_root=state_root
        )
        self.assertFalse(blocked.publishable)
        self.assertIn("all_nine_pairs_required", blocked.incomplete_reasons)

    def test_pair_fairness_mismatches_block_the_affected_delta(self):
        schedule, complete, state_root, cleanup = write_complete_records_and_receipts_for_test()
        self.addCleanup(cleanup.cleanup)
        cases = (
            ("baseline", "f" * 40, "baseline_mismatch"),
            ("subject_tree_hash", "e" * 40, "subject_tree_mismatch"),
            ("case_definition_hash", "d" * 64, "case_definition_mismatch"),
            ("scorer_version", "finding-overlap-v2", "run_contract_mismatch"),
            ("cli_version", "codex-cli 0.148.0", "run_contract_mismatch"),
            ("adapter_fingerprint", "c" * 64, "run_contract_mismatch"),
            ("routing_config_hash", "d" * 64, "run_contract_mismatch"),
            ("timeout_seconds", 121.0, "run_contract_mismatch"),
            ("sandbox", "workspace-write", "run_contract_mismatch"),
            ("acceptance_contract_hash", "b" * 64, "run_contract_mismatch"),
        )
        for field, value, reason in cases:
            with self.subTest(field=field):
                changed = (replace(complete[0], **{field: value}), *complete[1:])
                report = paired_codex.calculate_report(schedule, changed, state_root=state_root)
                self.assertFalse(report.publishable)
                self.assertIn(reason, report.incomplete_reasons)
                self.assertEqual(8, len(report.pairs))

    def test_cross_repetition_and_schedule_authority_mismatches_block_publication(self):
        schedule, complete, state_root, cleanup = write_complete_records_and_receipts_for_test()
        self.addCleanup(cleanup.cleanup)
        changed_index = next(
            index for index, record in enumerate(complete)
            if record.entry.case_id == "small" and record.entry.repetition == 2
        )
        for field, value, reason in (
            ("baseline", "f" * 40, "baseline_changed_across_repetitions"),
            ("subject_tree_hash", "e" * 40, "subject_tree_changed_across_repetitions"),
            ("case_definition_hash", "d" * 64, "case_definition_changed_across_repetitions"),
            ("routing_config_hash", "d" * 64, "run_contract_changed_across_repetitions"),
            ("scorer_version", "finding-overlap-v2", "run_contract_changed_across_repetitions"),
        ):
            with self.subTest(field=field):
                records = list(complete)
                records[changed_index] = replace(records[changed_index], **{field: value})
                report = paired_codex.calculate_report(schedule, records, state_root=state_root)
                self.assertFalse(report.publishable)
                self.assertIn(reason, report.incomplete_reasons)
        agreed_wrong = tuple(replace(record, routing_config_hash="d" * 64) for record in complete)
        report = paired_codex.calculate_report(schedule, agreed_wrong, state_root=state_root)
        self.assertFalse(report.publishable)
        self.assertIn("schedule_contract_mismatch", report.incomplete_reasons)

    def test_persisted_execution_plan_is_the_only_requested_settings_authority(self):
        schedule, complete, state_root, cleanup = write_complete_records_and_receipts_for_test()
        self.addCleanup(cleanup.cleanup)
        first = complete[0]
        invocation = first.invocations[0]
        for changes, reason in (
            ({"requested_model": "gpt-5.6-luna"}, "requested_model_mismatch"),
            ({"requested_reasoning_effort": "low"}, "requested_effort_mismatch"),
            ({"actual_model": "gpt-5.6-luna"}, "actual_model_mismatch"),
        ):
            with self.subTest(reason=reason):
                changed = replace(first, invocations=(replace(invocation, **changes),))
                report = paired_codex.calculate_report(
                    schedule, (changed, *complete[1:]), state_root=state_root
                )
                self.assertFalse(report.publishable)
                self.assertIn(reason, report.incomplete_reasons)

    def test_incomplete_malformed_truncated_and_zero_baseline_records_block_deltas(self):
        schedule, complete, state_root, cleanup = write_complete_records_and_receipts_for_test()
        self.addCleanup(cleanup.cleanup)
        first = complete[0]
        invocation = first.invocations[0]
        cases = (
            (replace(first, completion_state="incomplete", incomplete_reasons=("malformed_result",)),
             "malformed_result"),
            (replace(first, score=None), "incomplete_score"),
            (replace(first, invocations=(replace(invocation, status="failed"),)),
             "invocation_incomplete"),
            (replace(first, invocations=(replace(
                invocation, incomplete_reasons=("provider_output_limit",)
            ),)), "output_truncated"),
            (replace(first, invocations=(replace(invocation, total_tokens=None),)),
             "provider_usage_missing"),
            (replace(first, invocations=(replace(
                invocation, input_tokens=0, output_tokens=0, total_tokens=0
            ),)), "zero_sequential_tokens"),
            (replace(first, wall_seconds=0.0), "zero_sequential_time"),
        )
        for changed, reason in cases:
            with self.subTest(reason=reason):
                report = paired_codex.calculate_report(
                    schedule, (changed, *complete[1:]), state_root=state_root
                )
                self.assertFalse(report.publishable)
                self.assertIn(reason, report.incomplete_reasons)
                self.assertEqual(8, len(report.pairs))

    def test_receipts_are_reopened_immediately_before_report(self):
        schedule, records, state_root, cleanup = write_complete_records_and_receipts_for_test()
        self.addCleanup(cleanup.cleanup)
        self.assertTrue(paired_codex.calculate_report(
            schedule, records, state_root=state_root
        ).publishable)
        receipt = state_root / records[0].invocations[0].receipt
        receipt.write_text(json.dumps({"output_hash": "f" * 64}) + "\n", encoding="utf-8")
        receipt.chmod(0o600)
        report = paired_codex.calculate_report(schedule, records, state_root=state_root)
        self.assertFalse(report.publishable)
        self.assertIn("receipt_audit_failed", report.incomplete_reasons)

    def test_exact_delta_formulas_and_zero_denominators(self):
        delta = paired_codex.calculate_pair_delta(
            sequential_tokens=100,
            canopy_tokens=75,
            sequential_seconds=10.0,
            canopy_seconds=12.0,
            sequential_f1=0.5,
            canopy_f1=0.9,
        )
        self.assertEqual((-25.0, 20.0, 0.4), (
            delta.token_delta_percent, delta.time_delta_percent, delta.quality_delta
        ))
        for field in ("sequential_tokens", "sequential_seconds"):
            values = dict(
                sequential_tokens=100,
                canopy_tokens=75,
                sequential_seconds=10.0,
                canopy_seconds=12.0,
                sequential_f1=0.5,
                canopy_f1=0.9,
            )
            values[field] = 0
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "zero"):
                paired_codex.calculate_pair_delta(**values)

    def test_report_cli_loads_schedule_and_records_from_private_ledger(self):
        schedule, records, state_root, cleanup = write_complete_records_and_receipts_for_test()
        self.addCleanup(cleanup.cleanup)
        results = state_root / "results.jsonl"
        paired_codex.append_result_record(results, {"kind": "schedule", **asdict(schedule)})
        for record in records:
            paired_codex.append_result_record(results, {"kind": "arm-result", **asdict(record)})
        output = io.StringIO()
        with patch.object(paired_codex, "_build_command_schedule") as rebuild, redirect_stdout(output):
            status = paired_codex.main([
                "report", "--results", str(results), "--state-dir", str(state_root)
            ])
        self.assertEqual(0, status)
        self.assertTrue(json.loads(output.getvalue())["publishable"])
        rebuild.assert_not_called()

    def test_dry_run_commands_and_full_run_refusal_never_dispatch(self):
        for command in ("probe", "acceptance", "run"):
            with self.subTest(command=command), patch.object(
                paired_codex, "execute_provider"
            ) as execute, redirect_stdout(io.StringIO()):
                self.assertEqual(0, paired_codex.main([command]))
                execute.assert_not_called()
        schedule = fake_schedule()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            results = root / "results.jsonl"
            output = io.StringIO()
            with patch.object(
                paired_codex, "_build_command_schedule", return_value=(
                    schedule, fake_case_definitions(), fake_routing_config()
                )
            ), patch.object(paired_codex, "execute_provider") as execute, redirect_stdout(output):
                status = paired_codex.main([
                    "run", "--execute", "--results", str(results),
                    "--state-dir", str(root), "--seed", "41",
                ])
            loaded, records = paired_codex.load_results(results)
        self.assertEqual(1, status)
        self.assertEqual((schedule, ()), (loaded, records))
        self.assertIn("actual_model_unavailable", output.getvalue())
        execute.assert_not_called()

    def test_acceptance_executes_only_first_small_pair_with_mocked_arms(self):
        schedule, records, state_root, cleanup = write_complete_records_and_receipts_for_test()
        self.addCleanup(cleanup.cleanup)
        by_entry = {record.entry: record for record in records}
        calls = []

        def fake_runner(_case, entry, _config, _contract, _snapshot, _plan, **kwargs):
            calls.append(entry)
            return by_entry[entry]

        results = state_root / "acceptance.jsonl"
        output = io.StringIO()
        with patch.object(
            paired_codex, "_build_command_schedule", return_value=(
                schedule, fake_case_definitions(), fake_routing_config()
            )
        ), patch.object(
            paired_codex, "run_sequential_arm", side_effect=fake_runner
        ), patch.object(
            paired_codex, "run_canopy_arm", side_effect=fake_runner
        ), patch.object(paired_codex, "execute_provider") as execute, redirect_stdout(output):
            status = paired_codex.main([
                "acceptance", "--execute", "--results", str(results),
                "--state-dir", str(state_root), "--seed", "41",
            ])
        report = json.loads(output.getvalue())
        loaded_schedule, loaded_records = paired_codex.load_results(results)
        self.assertEqual(0, status)
        self.assertEqual(list(schedule.entries[:2]), calls)
        self.assertEqual({"small"}, {entry.case_id for entry in calls})
        self.assertEqual(schedule, loaded_schedule)
        self.assertEqual(tuple(by_entry[entry] for entry in calls), loaded_records)
        self.assertEqual(2, report["sample_count"])
        self.assertEqual(
            {
                invocation.receipt
                for record in loaded_records
                for invocation in record.invocations
            },
            {
                invocation.receipt
                for entry in calls
                for invocation in by_entry[entry].invocations
            },
        )
        self.assertFalse(report["publishable"])
        self.assertIn("all_nine_pairs_required", report["incomplete_reasons"])
        execute.assert_not_called()

    def test_acceptance_does_not_double_append_runner_interrupt_evidence(self):
        schedule, records, state_root, cleanup = write_complete_records_and_receipts_for_test()
        self.addCleanup(cleanup.cleanup)
        first = next(record for record in records if record.entry == schedule.entries[0])
        interrupted = replace(
            first,
            invocations=(),
            score=None,
            executed_nodes=0,
            failed_nodes=0,
            pruned_nodes=first.planned_nodes,
            completion_state="interrupted",
            incomplete_reasons=("interrupted",),
        )
        results = state_root / "interrupted-acceptance.jsonl"

        def interrupting_runner(*_args, **kwargs):
            paired_codex.append_result_record(
                kwargs["results_path"],
                {"kind": "arm-result", **asdict(interrupted)},
            )
            raise KeyboardInterrupt()

        with patch.object(
            paired_codex, "_build_command_schedule", return_value=(
                schedule, fake_case_definitions(), fake_routing_config()
            )
        ), patch.object(
            paired_codex, "run_sequential_arm", side_effect=interrupting_runner
        ), self.assertRaises(KeyboardInterrupt):
            paired_codex._acceptance_command(results, state_root, 41)
        loaded_schedule, loaded_records = paired_codex.load_results(results)
        self.assertEqual(schedule, loaded_schedule)
        self.assertEqual((interrupted,), loaded_records)

    def test_public_report_functions_fail_closed_on_non_arm_records(self):
        schedule, _, state_root, cleanup = write_complete_records_and_receipts_for_test()
        self.addCleanup(cleanup.cleanup)
        malformed = object()
        reasons = paired_codex.publication_gate(schedule, (malformed,), state_root)
        report = paired_codex.calculate_report(
            schedule, (malformed,), state_root=state_root
        )
        self.assertIn("malformed_result", reasons)
        self.assertIn("malformed_result", report.incomplete_reasons)
        self.assertFalse(report.publishable)
        self.assertEqual(1, report.sample_count)

    def test_seeded_schedule_has_nine_pairs_and_eighteen_unique_positions(self):
        contract = fake_run_contract()
        cases = fake_case_snapshots()
        definitions = fake_case_definitions()
        config = fake_routing_config()
        first = paired_codex.build_schedule(41, contract, cases, definitions, config)
        second = paired_codex.build_schedule(41, contract, cases, definitions, config)
        self.assertEqual(first, second)
        self.assertEqual(18, len(first.entries))
        self.assertEqual(list(range(18)), [entry.position for entry in first.entries])
        self.assertEqual(
            [
                "sequential", "canopy", "sequential", "canopy", "canopy", "sequential",
                "canopy", "sequential", "sequential", "canopy", "sequential", "canopy",
                "sequential", "canopy", "sequential", "canopy", "canopy", "sequential",
            ],
            [entry.arm for entry in first.entries],
        )
        pairs = {(entry.case_id, entry.repetition) for entry in first.entries}
        self.assertEqual(9, len(pairs))
        for pair in pairs:
            self.assertEqual(
                {"sequential", "canopy"},
                {
                    entry.arm
                    for entry in first.entries
                    if (entry.case_id, entry.repetition) == pair
                },
            )
        with self.assertRaises(FrozenInstanceError):
            first.entries[0].arm = "changed"

    def test_schedule_persists_exact_frozen_execution_plans(self):
        schedule = fake_schedule()
        small_sequential = next(
            plan for plan in schedule.execution_plans
            if (plan.case_id, plan.arm) == ("small", "sequential")
        )
        small_canopy = next(
            plan for plan in schedule.execution_plans
            if (plan.case_id, plan.arm) == ("small", "canopy")
        )
        self.assertEqual(
            (("lead", "gpt-5.6-sol", "high"),),
            tuple((item.node_id, item.requested_model, item.requested_reasoning_effort)
                  for item in small_sequential.invocations),
        )
        self.assertEqual(
            (("percentage", "gpt-5.6-luna", "medium"),
             ("reviewer", "gpt-5.6-terra", "high")),
            tuple((item.node_id, item.requested_model, item.requested_reasoning_effort)
                  for item in small_canopy.invocations),
        )
        with self.assertRaises(FrozenInstanceError):
            small_canopy.invocations[0].requested_model = "changed"
        config = fake_routing_config()
        frozen = paired_codex.build_schedule(
            41, fake_run_contract(), fake_case_snapshots(), fake_case_definitions(), config
        )
        config.models["lead"] = ModelSettings("changed", "low")
        sequential = next(
            plan for plan in frozen.execution_plans
            if (plan.case_id, plan.arm) == ("small", "sequential")
        )
        self.assertEqual("gpt-5.6-sol", sequential.invocations[0].requested_model)

    def test_schedule_requires_canonical_contract_and_exact_case_snapshots(self):
        contract = fake_run_contract()
        cases = fake_case_snapshots()
        definitions = fake_case_definitions()
        config = fake_routing_config()
        canonical = paired_codex.build_schedule(41, contract, cases, definitions, config)
        reordered = paired_codex.build_schedule(
            41, contract, tuple(reversed(cases)), definitions, config
        )
        self.assertEqual(canonical, reordered)
        invalid_inputs = (
            (contract, cases[:-1]),
            (contract, (cases[0], cases[0], cases[2])),
            (contract, (replace(cases[0], case_id=["small"]), *cases[1:])),
            (contract, (replace(cases[0], baseline="not-a-hash"), *cases[1:])),
            (replace(contract, routing_config_hash="not-a-hash"), cases),
        )
        for invalid_contract, invalid_cases in invalid_inputs:
            with self.subTest(contract=invalid_contract, cases=invalid_cases):
                with self.assertRaises(ValueError):
                    paired_codex.build_schedule(
                        41, invalid_contract, invalid_cases, definitions, config
                    )

    def test_result_record_is_canonical_private_and_durable(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "private" / "results.jsonl"
            paired_codex.append_result_record(path, {"z": 1, "a": "value"})
            self.assertEqual(b'{"a":"value","z":1}\n', path.read_bytes())
            self.assertEqual(0o600, stat.S_IMODE(path.stat().st_mode))

    def test_result_limits_leave_existing_ledger_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "results.jsonl"
            paired_codex.append_result_record(path, {"kind": "schedule", "entries": []})
            original = path.read_bytes()
            with patch.object(paired_codex, "MAX_RESULT_EVENTS", 1):
                with self.assertRaisesRegex(ValueError, "event limit"):
                    paired_codex.append_result_record(path, {"kind": "arm-result"})
            self.assertEqual(original, path.read_bytes())

    def test_result_rejects_preexisting_oversize_before_scanning(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "results.jsonl"
            path.write_bytes(b"x" * (paired_codex.MAX_RESULT_BYTES + 1))
            original = path.read_bytes()
            with self.assertRaisesRegex(ValueError, "size limit"):
                paired_codex.append_result_record(path, {"kind": "arm-result"})
            self.assertEqual(original, path.read_bytes())

    def test_result_rejects_preexisting_oversized_event_without_mutation(self):
        existing = json.dumps(
            {"kind": "arm-result", "padding": "x" * paired_codex.MAX_RESULT_EVENT_BYTES},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8") + b"\n"
        self.assertGreater(len(existing), paired_codex.MAX_RESULT_EVENT_BYTES)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "results.jsonl"
            path.write_bytes(existing)
            path.chmod(0o600)
            original = path.read_bytes()
            with self.assertRaisesRegex(ValueError, "event size limit"):
                paired_codex.append_result_record(path, {"kind": "arm-result"})
            self.assertEqual(original, path.read_bytes())

    def test_result_enforces_exact_event_size_boundary(self):
        overhead = len(b'{"payload":""}\n')
        exact = {"payload": "x" * (paired_codex.MAX_RESULT_EVENT_BYTES - overhead)}
        oversized = {"payload": exact["payload"] + "x"}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "results.jsonl"
            paired_codex.append_result_record(path, exact)
            original = path.read_bytes()
            self.assertEqual(paired_codex.MAX_RESULT_EVENT_BYTES, len(original))
            with self.assertRaisesRegex(ValueError, "event size limit"):
                paired_codex.append_result_record(path, oversized)
            self.assertEqual(original, path.read_bytes())

    def test_result_rejects_the_event_after_one_thousand_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "results.jsonl"
            path.write_bytes(b'{}\n' * paired_codex.MAX_RESULT_EVENTS)
            original = path.read_bytes()
            with self.assertRaisesRegex(ValueError, "event limit"):
                paired_codex.append_result_record(path, {"kind": "arm-result"})
            self.assertEqual(original, path.read_bytes())

    def test_result_rejects_symlinks_and_hard_links_without_changing_targets(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for link_kind in ("symlink", "hardlink"):
                with self.subTest(link_kind=link_kind):
                    target = root / f"{link_kind}-target"
                    target.write_bytes(b"untouched")
                    result = root / f"{link_kind}-results.jsonl"
                    if link_kind == "symlink":
                        result.symlink_to(target)
                    else:
                        os.link(target, result)
                    with self.assertRaises(ValueError):
                        paired_codex.append_result_record(result, {"kind": "arm-result"})
                    self.assertEqual(b"untouched", target.read_bytes())

    def test_result_loader_constructs_the_exact_first_schedule(self):
        schedule = fake_schedule()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "results.jsonl"
            paired_codex.append_result_record(path, {"kind": "schedule", **asdict(schedule)})
            loaded, records = paired_codex.load_results(path)
        self.assertEqual(schedule, loaded)
        self.assertEqual((), records)

    def test_result_loader_rejects_noncanonical_execution_plan_snapshots(self):
        schedule = fake_schedule()
        canonical = {"kind": "schedule", **asdict(schedule)}

        def nested_junk(row):
            row["execution_plans"][0]["invocations"][0]["junk"] = True

        def reordered(row):
            row["execution_plans"][0], row["execution_plans"][1] = (
                row["execution_plans"][1], row["execution_plans"][0]
            )

        def unknown_effort(row):
            row["execution_plans"][0]["invocations"][0][
                "requested_reasoning_effort"
            ] = "unbounded"

        for name, mutate in (
            ("nested_junk", nested_junk),
            ("reordered", reordered),
            ("unknown_effort", unknown_effort),
        ):
            row = json.loads(json.dumps(canonical))
            mutate(row)
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "results.jsonl"
                paired_codex.append_result_record(path, row)
                with self.assertRaisesRegex(
                    ValueError, "execution plan|planned invocation"
                ):
                    paired_codex.load_results(path)

    def test_result_loader_rejects_unknown_keys_and_later_schedule_rows(self):
        schedule = fake_schedule()
        record = {"kind": "schedule", **asdict(schedule)}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "results.jsonl"
            paired_codex.append_result_record(path, record)
            paired_codex.append_result_record(path, record)
            original = path.read_bytes()
            with self.assertRaisesRegex(ValueError, "schedule"):
                paired_codex.load_results(path)
            self.assertEqual(original, path.read_bytes())

    def test_result_loader_reconstructs_nested_typed_arm_records(self):
        schedule = fake_schedule()
        record = complete_arm_record(schedule)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "results.jsonl"
            paired_codex.append_result_record(path, {"kind": "schedule", **asdict(schedule)})
            paired_codex.append_result_record(path, {"kind": "arm-result", **asdict(record)})
            loaded_schedule, loaded_records = paired_codex.load_results(path)
        self.assertEqual(schedule, loaded_schedule)
        self.assertEqual((record,), loaded_records)
        self.assertIsInstance(loaded_records[0], paired_codex.ArmRecord)
        self.assertIsInstance(loaded_records[0].entry, paired_codex.ScheduleEntry)
        self.assertIsInstance(loaded_records[0].invocations[0], paired_codex.InvocationRecord)
        self.assertIsInstance(loaded_records[0].score, paired_codex.Score)

    def test_producer_snapshot_mismatch_records_round_trip_before_dispatch(self):
        case = paired_codex.load_case_definition(paired_codex.CASE_ROOT / "small")
        actual = real_case_snapshot(case)

        def different(value):
            digit = "0" if value[0] != "0" else "1"
            return digit * len(value)

        variants = (
            ({"baseline": different(actual.baseline)}, ("baseline_mismatch",), "sequential"),
            ({"subject_tree_hash": different(actual.subject_tree_hash)},
             ("subject_tree_hash_mismatch",), "sequential"),
            ({"case_definition_hash": different(actual.case_definition_hash)},
             ("case_definition_hash_mismatch",), "sequential"),
            ({
                "baseline": different(actual.baseline),
                "subject_tree_hash": different(actual.subject_tree_hash),
                "case_definition_hash": different(actual.case_definition_hash),
            }, (
                "baseline_mismatch",
                "subject_tree_hash_mismatch",
                "case_definition_hash_mismatch",
            ), "canopy"),
        )
        definitions = fake_case_definitions()
        config = fake_routing_config()
        for changes, expected_reasons, arm in variants:
            with self.subTest(arm=arm, reasons=expected_reasons):
                snapshot = replace(actual, **changes)
                other = fake_case_snapshots()[1:]
                schedule = paired_codex.build_schedule(
                    41, fake_run_contract(), (snapshot, *other), definitions, config
                )
                entry = next(
                    item for item in schedule.entries
                    if (item.case_id, item.repetition, item.arm) == ("small", 1, arm)
                )
                plan = next(
                    item for item in schedule.execution_plans
                    if (item.case_id, item.arm) == ("small", arm)
                )
                with tempfile.TemporaryDirectory() as directory:
                    runner = (
                        paired_codex.run_sequential_arm
                        if arm == "sequential"
                        else paired_codex.run_canopy_arm
                    )
                    record = runner(
                        case, entry, config, fake_run_contract(), snapshot, plan,
                        seed=41,
                        state_root=Path(directory),
                        execute=lambda _request: self.fail("snapshot mismatch dispatched"),
                        capability=fake_capability,
                    )
                    path = Path(directory) / "results.jsonl"
                    paired_codex.append_result_record(
                        path, {"kind": "schedule", **asdict(schedule)}
                    )
                    paired_codex.append_result_record(
                        path, {"kind": "arm-result", **asdict(record)}
                    )
                    _, loaded = paired_codex.load_results(path)
                self.assertEqual((record,), loaded)
                self.assertEqual(expected_reasons, record.incomplete_reasons)
                self.assertEqual("incomplete", record.completion_state)
                self.assertEqual((), record.invocations)
                self.assertIsNone(record.score)

    def test_result_loader_rejects_forged_snapshot_mismatch_shapes(self):
        schedule = fake_schedule()
        canonical = {"kind": "arm-result", **asdict(complete_arm_record(schedule))}
        changed_baseline = "f" * 40
        if changed_baseline == canonical["baseline"]:
            changed_baseline = "e" * 40

        def mismatch_after_dispatch(row):
            row["baseline"] = changed_baseline
            row["score"] = None
            row["completion_state"] = "incomplete"
            row["incomplete_reasons"] = ["baseline_mismatch"]

        def mismatch_without_exact_reason(row):
            row.update(
                baseline=changed_baseline,
                invocations=[],
                score=None,
                executed_nodes=0,
                failed_nodes=0,
                pruned_nodes=1,
                completion_state="incomplete",
                incomplete_reasons=["subject_tree_hash_mismatch"],
            )

        def forged_reason_without_mismatch(row):
            row.update(
                invocations=[],
                score=None,
                executed_nodes=0,
                failed_nodes=0,
                pruned_nodes=1,
                completion_state="incomplete",
                incomplete_reasons=["baseline_mismatch"],
            )

        for name, mutate in (
            ("mismatch_after_dispatch", mismatch_after_dispatch),
            ("mismatch_without_exact_reason", mismatch_without_exact_reason),
            ("forged_reason_without_mismatch", forged_reason_without_mismatch),
        ):
            row = json.loads(json.dumps(canonical))
            mutate(row)
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "results.jsonl"
                paired_codex.append_result_record(
                    path, {"kind": "schedule", **asdict(schedule)}
                )
                paired_codex.append_result_record(path, row)
                with self.assertRaisesRegex(ValueError, "arm result"):
                    paired_codex.load_results(path)

    def test_result_loader_rejects_invalid_arm_rows_fail_closed(self):
        schedule = fake_schedule()
        valid = {"kind": "arm-result", **asdict(complete_arm_record(schedule))}

        def extra_key(row):
            row["junk"] = True

        def missing_key(row):
            row.pop("score")

        def wrong_type(row):
            row["wall_seconds"] = "1.25"

        def non_finite(row):
            row["wall_seconds"] = math.nan

        def contract_mismatch(row):
            row["routing_config_hash"] = "e" * 64

        def nested_junk(row):
            row["invocations"][0]["junk"] = True

        for name, mutate in (
            ("extra", extra_key),
            ("missing", missing_key),
            ("wrong_type", wrong_type),
            ("non_finite", non_finite),
            ("contract_mismatch", contract_mismatch),
            ("nested_junk", nested_junk),
        ):
            row = json.loads(json.dumps(valid))
            mutate(row)
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "results.jsonl"
                paired_codex.append_result_record(
                    path, {"kind": "schedule", **asdict(schedule)}
                )
                with path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(row, separators=(",", ":")) + "\n")
                original = path.read_bytes()
                with self.assertRaisesRegex(ValueError, "arm result"):
                    paired_codex.load_results(path)
                self.assertEqual(original, path.read_bytes())

    def test_result_loader_rejects_impossible_normalized_arm_states(self):
        schedule = fake_schedule()
        sequential = {"kind": "arm-result", **asdict(complete_arm_record(schedule))}
        canopy = {"kind": "arm-result", **asdict(complete_canopy_record(schedule))}

        def duplicate_lead_and_receipt(row):
            row["invocations"].append(dict(row["invocations"][0]))
            row["planned_nodes"] = 2
            row["executed_nodes"] = 2

        def fallback_used(row):
            row["invocations"][0]["fallback_used"] = True

        def missing_actual_model_evidence(row):
            row["invocations"][0]["actual_model"] = None

        def accepted_below_threshold(row):
            row["score"] = {
                "tp": 1,
                "fp": 1,
                "fn": 0,
                "precision": 0.5,
                "recall": 1.0,
                "f1": 2 / 3,
                "accepted": True,
            }

        def rejected_despite_complete_threshold_score(row):
            row["score"]["accepted"] = False

        def arbitrary_lead_settings(row):
            row["invocations"][0]["requested_model"] = "gpt-5.6-luna"

        def bogus_extra_canopy_leaf(row):
            bogus = dict(row["invocations"][0])
            bogus["node_id"] = "bogus"
            bogus["receipt"] = (
                f"receipts/{row['entry']['position']:03d}-{row['entry']['case_id']}-canopy/"
                "bogus.jsonl"
            )
            row["invocations"].insert(-1, bogus)
            row["planned_nodes"] = 3
            row["executed_nodes"] = 3

        def noncanonical_receipt(row):
            row["invocations"][0]["receipt"] = "receipts/other/lead.jsonl"

        def failed_without_evidence(row):
            row["invocations"][0]["status"] = "failed"
            row["invocations"][0]["exit_code"] = 7
            row["failed_nodes"] = 1

        def duplicate_canopy_receipt(row):
            row["invocations"][1]["receipt"] = row["invocations"][0]["receipt"]

        def scored_canopy_without_reviewer(row):
            row["invocations"] = row["invocations"][:1]
            row["executed_nodes"] = 1
            row["pruned_nodes"] = 1

        def reviewer_not_last(row):
            row["invocations"].reverse()

        cases = (
            ("duplicate_lead_and_receipt", sequential, duplicate_lead_and_receipt),
            ("fallback_used", sequential, fallback_used),
            ("missing_actual_model_evidence", sequential, missing_actual_model_evidence),
            ("accepted_below_threshold", sequential, accepted_below_threshold),
            ("rejected_despite_complete_threshold_score", sequential,
             rejected_despite_complete_threshold_score),
            ("arbitrary_lead_settings", sequential, arbitrary_lead_settings),
            ("noncanonical_receipt", sequential, noncanonical_receipt),
            ("failed_without_evidence", sequential, failed_without_evidence),
            ("duplicate_canopy_receipt", canopy, duplicate_canopy_receipt),
            ("bogus_extra_canopy_leaf", canopy, bogus_extra_canopy_leaf),
            ("scored_canopy_without_reviewer", canopy, scored_canopy_without_reviewer),
            ("reviewer_not_last", canopy, reviewer_not_last),
        )
        for name, template, mutate in cases:
            row = json.loads(json.dumps(template))
            mutate(row)
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "results.jsonl"
                paired_codex.append_result_record(
                    path, {"kind": "schedule", **asdict(schedule)}
                )
                paired_codex.append_result_record(path, row)
                original = path.read_bytes()
                with self.assertRaisesRegex(ValueError, "arm result"):
                    paired_codex.load_results(path)
                self.assertEqual(original, path.read_bytes())

    def test_rejected_score_with_nonzero_fn_remains_possible_without_severity_identities(self):
        schedule = fake_schedule()
        row = {"kind": "arm-result", **asdict(complete_arm_record(schedule))}
        row["score"] = {
            "tp": 4,
            "fp": 0,
            "fn": 1,
            "precision": 1.0,
            "recall": 0.8,
            "f1": 2 * 1.0 * 0.8 / (1.0 + 0.8),
            "accepted": False,
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "results.jsonl"
            paired_codex.append_result_record(path, {"kind": "schedule", **asdict(schedule)})
            paired_codex.append_result_record(path, row)
            _, records = paired_codex.load_results(path)
        self.assertFalse(records[0].score.accepted)

    def test_result_loader_preserves_only_legitimate_interrupted_prefixes(self):
        schedule = fake_schedule()
        sequential = {"kind": "arm-result", **asdict(complete_arm_record(schedule))}
        sequential.update(
            invocations=[],
            score=None,
            executed_nodes=0,
            pruned_nodes=1,
            completion_state="interrupted",
            incomplete_reasons=["interrupted"],
        )
        canopy = {"kind": "arm-result", **asdict(complete_canopy_record(schedule))}
        canopy.update(
            invocations=canopy["invocations"][:1],
            score=None,
            executed_nodes=1,
            pruned_nodes=1,
            completion_state="interrupted",
            incomplete_reasons=["interrupted"],
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "results.jsonl"
            paired_codex.append_result_record(path, {"kind": "schedule", **asdict(schedule)})
            paired_codex.append_result_record(path, sequential)
            paired_codex.append_result_record(path, canopy)
            _, records = paired_codex.load_results(path)
        self.assertEqual(("interrupted", "interrupted"), tuple(
            record.completion_state for record in records
        ))
        self.assertEqual((0, 1), tuple(len(record.invocations) for record in records))

    def test_result_loader_rejects_contradictory_interrupted_states(self):
        schedule = fake_schedule()
        sequential = {"kind": "arm-result", **asdict(complete_arm_record(schedule))}
        canopy = {"kind": "arm-result", **asdict(complete_canopy_record(schedule))}

        def incomplete_with_interrupted_reason(row):
            row.update(
                invocations=[], score=None, executed_nodes=0, pruned_nodes=1,
                completion_state="incomplete", incomplete_reasons=["interrupted"],
            )

        def interrupted_completed_lead(row):
            row.update(completion_state="interrupted", incomplete_reasons=["interrupted"])

        def interrupted_completed_reviewer(row):
            row.update(completion_state="interrupted", incomplete_reasons=["interrupted"])

        def interrupted_canopy_with_reviewer_no_score(row):
            row.update(
                score=None, completion_state="interrupted", incomplete_reasons=["interrupted"]
            )

        for name, template, mutate in (
            ("incomplete_with_interrupted_reason", sequential,
             incomplete_with_interrupted_reason),
            ("interrupted_completed_lead", sequential, interrupted_completed_lead),
            ("interrupted_completed_reviewer", canopy, interrupted_completed_reviewer),
            ("interrupted_canopy_with_reviewer_no_score", canopy,
             interrupted_canopy_with_reviewer_no_score),
        ):
            row = json.loads(json.dumps(template))
            mutate(row)
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "results.jsonl"
                paired_codex.append_result_record(
                    path, {"kind": "schedule", **asdict(schedule)}
                )
                paired_codex.append_result_record(path, row)
                with self.assertRaisesRegex(ValueError, "arm result"):
                    paired_codex.load_results(path)

    def test_result_loader_rejects_boolean_schedule_positions(self):
        schedule = fake_schedule()
        record = {"kind": "schedule", **asdict(schedule)}
        record["entries"][0]["position"] = False
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "results.jsonl"
            paired_codex.append_result_record(path, record)
            original = path.read_bytes()
            with self.assertRaisesRegex(ValueError, "schedule entry"):
                paired_codex.load_results(path)
            self.assertEqual(original, path.read_bytes())
            path.write_bytes(json.dumps({**record, "unknown": True}).encode() + b"\n")
            path.chmod(0o600)
            original = path.read_bytes()
            with self.assertRaisesRegex(ValueError, "schedule"):
                paired_codex.load_results(path)
            self.assertEqual(original, path.read_bytes())

    def test_receipt_auditor_requires_one_matching_output_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            receipt = root / "receipts" / "000-small-sequential" / "lead.jsonl"
            receipt.parent.mkdir(parents=True)
            receipt.write_text(json.dumps({"output_hash": "a" * 64}) + "\n", encoding="utf-8")
            receipt.chmod(0o600)
            reference = receipt.relative_to(root).as_posix()
            paired_codex.audit_proof_receipt(root, reference, "a" * 64)
            with self.assertRaisesRegex(ValueError, "output hash"):
                paired_codex.audit_proof_receipt(root, reference, "b" * 64)
            receipt.write_text(receipt.read_text() * 2, encoding="utf-8")
            original = receipt.read_bytes()
            with self.assertRaisesRegex(ValueError, "exactly one"):
                paired_codex.audit_proof_receipt(root, reference, "a" * 64)
            self.assertEqual(original, receipt.read_bytes())

    def test_receipt_auditor_rejects_unsafe_paths_links_and_oversize(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "target.jsonl"
            target.write_text(json.dumps({"output_hash": "a" * 64}) + "\n", encoding="utf-8")
            target.chmod(0o600)
            for reference in ("/absolute.jsonl", "../parent.jsonl", "receipts\\backslash.jsonl"):
                with self.subTest(reference=reference), self.assertRaises(ValueError):
                    paired_codex.audit_proof_receipt(root, reference, "a" * 64)
            for link_kind in ("symlink", "hardlink"):
                with self.subTest(link_kind=link_kind):
                    linked = root / f"{link_kind}.jsonl"
                    if link_kind == "symlink":
                        linked.symlink_to(target)
                    else:
                        os.link(target, linked)
                    original = target.read_bytes()
                    with self.assertRaises(ValueError):
                        paired_codex.audit_proof_receipt(root, linked.name, "a" * 64)
                    self.assertEqual(original, target.read_bytes())
            oversized = root / "oversized.jsonl"
            oversized.write_bytes(b"x" * (paired_codex.MAX_RECEIPT_EVENT_BYTES + 1))
            oversized.chmod(0o600)
            original = oversized.read_bytes()
            with self.assertRaisesRegex(ValueError, "size limit"):
                paired_codex.audit_proof_receipt(root, oversized.name, "a" * 64)
            self.assertEqual(original, oversized.read_bytes())

    def test_model_finding_parser_normalizes_manifest_paths(self):
        case = paired_codex.load_case_definition(paired_codex.CASE_ROOT / "small")
        parsed = paired_codex.parse_model_findings(json.dumps({"findings": [{
            "file": "subject/./percentage.py",
            "start_line": 2,
            "end_line": 2,
            "category": "correctness",
            "severity": "medium",
            "summary": "division by zero",
        }]}), case)
        self.assertEqual((), parsed.incomplete_reasons)
        self.assertEqual((paired_codex.Finding(
            "subject/percentage.py", 2, 2, "correctness", "medium", "division by zero"
        ),), parsed.findings)

    def test_model_finding_parser_marks_malformed_or_oversized_output_incomplete(self):
        case = paired_codex.load_case_definition(paired_codex.CASE_ROOT / "small")
        for output in ("not JSON", " " * (paired_codex.MAX_MODEL_FINDINGS_BYTES + 1)):
            with self.subTest(output_size=len(output)):
                parsed = paired_codex.parse_model_findings(output, case)
                self.assertIsNone(parsed.findings)
                self.assertTrue(parsed.incomplete_reasons)

    def test_model_finding_parser_requires_the_oracle_contract(self):
        case = paired_codex.load_case_definition(paired_codex.CASE_ROOT / "small")
        valid = {
            "file": "subject/percentage.py",
            "start_line": 2,
            "end_line": 2,
            "category": "correctness",
            "severity": "medium",
            "summary": "division by zero",
        }
        invalid_findings = (
            {**valid, "extra": "field"},
            {**valid, "file": "task.txt"},
            {**valid, "category": "unknown"},
            {**valid, "severity": "unknown"},
            {**valid, "start_line": 0},
            {**valid, "start_line": 2, "end_line": 1},
            {**valid, "end_line": 3},
            {**valid, "summary": ""},
        )
        for finding in invalid_findings:
            with self.subTest(finding=finding):
                parsed = paired_codex.parse_model_findings(json.dumps({"findings": [finding]}), case)
                self.assertIsNone(parsed.findings)
                self.assertTrue(parsed.incomplete_reasons)

    def test_model_schema_requires_summary_and_normalizes_only_after_validation(self):
        case = paired_codex.load_case_definition(paired_codex.CASE_ROOT / "small")
        prediction = {
            "file": "subject/percentage.py",
            "start_line": 2,
            "end_line": 2,
            "category": "correctness",
            "severity": "medium",
            "summary": "zero denominator",
        }
        parsed = paired_codex.parse_model_findings(
            json.dumps({"findings": [prediction]}), case
        )
        self.assertEqual("zero denominator", parsed.findings[0].description)
        for invalid in (
            {**prediction, "description": prediction["summary"]},
            {key: value for key, value in prediction.items() if key != "summary"} | {
                "description": prediction["summary"]
            },
        ):
            with self.subTest(invalid=invalid):
                rejected = paired_codex.parse_model_findings(
                    json.dumps({"findings": [invalid]}), case
                )
                self.assertIsNone(rejected.findings)
                self.assertIn("invalid_model_findings", rejected.incomplete_reasons)

    def test_oracle_schema_remains_exactly_description(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "small"
            shutil.copytree(paired_codex.CASE_ROOT / "small", root)
            self.assertTrue(paired_codex.load_case_definition(root).oracle)
            oracle = root / "oracle.json"
            oracle.write_text(
                oracle.read_text(encoding="utf-8").replace('"description"', '"summary"'),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "oracle findings"):
                paired_codex.load_case_definition(root)

    def test_scorer_is_one_to_one_and_counts_duplicates_as_false_positives(self):
        expected = (
            paired_codex.Finding("subject/a.py", 10, 12, "security", "high", "expected"),
        )
        predicted = (
            paired_codex.Finding("subject/a.py", 10, 10, "security", "high", "first"),
            paired_codex.Finding("subject/a.py", 11, 11, "security", "high", "duplicate"),
        )
        score = paired_codex.score_findings(expected, predicted)
        self.assertEqual((1, 1, 0), (score.tp, score.fp, score.fn))
        self.assertEqual((0.5, 1.0, 2 / 3), (score.precision, score.recall, score.f1))
        self.assertFalse(score.accepted)

    def test_zero_predictions_scores_exactly_zero(self):
        expected = (
            paired_codex.Finding("subject/a.py", 1, 1, "correctness", "medium", "expected"),
        )
        score = paired_codex.score_findings(expected, ())
        self.assertEqual((0, 0, 1, 0.0, 0.0, 0.0, False), (
            score.tp, score.fp, score.fn, score.precision, score.recall, score.f1, score.accepted
        ))

    def test_unmatched_high_finding_blocks_acceptance(self):
        expected = (
            paired_codex.Finding("subject/a.py", 1, 1, "security", "high", "required"),
            paired_codex.Finding("subject/b.py", 1, 1, "correctness", "low", "minor"),
        )
        predicted = (
            paired_codex.Finding("subject/b.py", 1, 1, "correctness", "low", "found"),
        )
        self.assertFalse(paired_codex.score_findings(expected, predicted).accepted)

    def test_case_hash_binds_manifest_dag_and_oracle(self):
        case = paired_codex.load_case_definition(paired_codex.CASE_ROOT / "small")
        original = paired_codex.canonical_case_definition_hash(case)
        with tempfile.TemporaryDirectory() as directory:
            copied = Path(directory) / "small"
            shutil.copytree(paired_codex.CASE_ROOT / "small", copied)
            oracle = copied / "oracle.json"
            oracle.write_text(oracle.read_text().replace('"medium"', '"high"'), encoding="utf-8")
            changed = paired_codex.canonical_case_definition_hash(
                paired_codex.load_case_definition(copied)
            )
        self.assertNotEqual(original, changed)

    def test_provider_repository_contains_only_manifest_files(self):
        case = paired_codex.load_case_definition(paired_codex.CASE_ROOT / "medium")
        with tempfile.TemporaryDirectory() as directory:
            repo, baseline, tree_hash = paired_codex.copy_case_repo(case, Path(directory))
            tracked = subprocess.run(
                ["git", "-C", str(repo), "ls-files"], check=True, capture_output=True, text=True
            ).stdout.splitlines()
            visible = sorted(
                path.relative_to(repo).as_posix()
                for path in repo.rglob("*")
                if path.is_file() and ".git" not in path.parts
            )
        self.assertEqual(list(case.copy_manifest), sorted(tracked))
        self.assertEqual(list(case.copy_manifest), visible)
        self.assertNotIn("oracle.json", visible)
        self.assertNotIn("dag.json", visible)
        self.assertRegex(baseline, r"^[0-9a-f]{40,64}$")
        self.assertRegex(tree_hash, r"^[0-9a-f]{40,64}$")

    def test_baseline_commit_ignores_parent_git_identity_environment(self):
        case = paired_codex.load_case_definition(paired_codex.CASE_ROOT / "small")
        first_identity = {
            "GIT_AUTHOR_NAME": "First Author",
            "GIT_AUTHOR_EMAIL": "first@example.test",
            "GIT_COMMITTER_NAME": "First Committer",
            "GIT_COMMITTER_EMAIL": "first-committer@example.test",
        }
        second_identity = {
            "GIT_AUTHOR_NAME": "Second Author",
            "GIT_AUTHOR_EMAIL": "second@example.test",
            "GIT_COMMITTER_NAME": "Second Committer",
            "GIT_COMMITTER_EMAIL": "second-committer@example.test",
        }
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, first_identity):
                _, first, _ = paired_codex.copy_case_repo(case, Path(directory) / "first")
            with patch.dict(os.environ, second_identity):
                _, second, _ = paired_codex.copy_case_repo(case, Path(directory) / "second")
        self.assertEqual(first, second)

    def test_case_loader_rejects_invalid_paths_and_schema(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "case"
            (root / "subject").mkdir(parents=True)
            (root / "task.txt").write_text("review", encoding="utf-8")
            (root / "subject" / "one.py").write_text("pass\n", encoding="utf-8")
            (root / "copy-manifest.json").write_text(
                '{"paths":["task.txt","subject/one.py"]}', encoding="utf-8"
            )
            (root / "dag.json").write_text(
                '{"nodes":[{"complexity_score":0.1,"id":"one","role":"worker",'
                '"scope":["subject/one.py"],"size_score":0.1}]}', encoding="utf-8"
            )
            (root / "oracle.json").write_text(
                '{"findings":[{"category":"correctness","description":"defect",'
                '"end_line":1,"file":"subject/one.py","severity":"medium","start_line":1}]}',
                encoding="utf-8",
            )
            paired_codex.load_case_definition(root)
            for path in ("/task.txt", "../task.txt", "subject\\one.py"):
                (root / "copy-manifest.json").write_text(
                    json.dumps({"paths": [path]}), encoding="utf-8"
                )
                with self.assertRaises(ValueError):
                    paired_codex.load_case_definition(root)
            (root / "copy-manifest.json").write_text(
                '{"paths":["task.txt","task.txt"]}', encoding="utf-8"
            )
            with self.assertRaises(ValueError):
                paired_codex.load_case_definition(root)
            (root / "copy-manifest.json").write_text(
                '{"paths":["task.txt","outside.py"]}', encoding="utf-8"
            )
            with self.assertRaises(ValueError):
                paired_codex.load_case_definition(root)
            (root / "copy-manifest.json").write_text(
                '{"paths":["task.txt","subject/missing.py"]}', encoding="utf-8"
            )
            with self.assertRaises(ValueError):
                paired_codex.load_case_definition(root)

    def test_case_loader_rejects_invalid_oracle_and_dag_contracts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "case"
            shutil.copytree(paired_codex.CASE_ROOT / "small", root)
            (root / "oracle.json").write_text(
                '{"findings":[{"category":"correctness","description":"one",'
                '"end_line":2,"file":"subject/percentage.py","severity":"medium","start_line":2},'
                '{"category":"correctness","description":"two","end_line":2,'
                '"file":"subject/percentage.py","severity":"medium","start_line":2}]}',
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                paired_codex.load_case_definition(root)
            (root / "oracle.json").write_text(
                '{"findings":[{"category":"unknown","description":"one",'
                '"end_line":2,"file":"subject/percentage.py","severity":"unknown","start_line":2}]}',
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                paired_codex.load_case_definition(root)
            (root / "oracle.json").write_bytes(
                (paired_codex.CASE_ROOT / "small" / "oracle.json").read_bytes()
            )
            for forbidden_key in ("model", "provider"):
                (root / "dag.json").write_text(
                    json.dumps({"nodes": [{
                        "complexity_score": 0.1,
                        "id": "one",
                        forbidden_key: "codex",
                        "role": "worker",
                        "scope": ["subject/percentage.py"],
                        "size_score": 0.1,
                    }]}),
                    encoding="utf-8",
                )
                with self.assertRaises(ValueError):
                    paired_codex.load_case_definition(root)
            (root / "dag.json").write_text(
                '{"nodes":[{"complexity_score":0.1,"id":"one","role":"worker",'
                '"scope":["subject/percentage.py"],"size_score":0.1},'
                '{"complexity_score":0.2,"id":"two","role":"worker",'
                '"scope":["subject/percentage.py"],"size_score":0.2}]}',
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                paired_codex.load_case_definition(root)

    def test_observed_schema_parses_cumulative_usage_without_model_inference(self):
        result = paired_codex.parse_jsonl(OBSERVED_JSONL)
        self.assertEqual((20, 4, 0, 5, 1, 25), (
            result.input_tokens,
            result.cached_input_tokens,
            result.cache_write_input_tokens,
            result.output_tokens,
            result.reasoning_output_tokens,
            result.total_tokens,
        ))
        self.assertEqual("REDACTED", result.final_response)
        self.assertIsNone(result.actual_model)
        self.assertIn("actual_model_unavailable", result.incomplete_reasons)

    def test_duplicate_or_invalid_usage_is_incomplete(self):
        duplicate = OBSERVED_JSONL + "\n" + json.dumps({
            "type": "turn.completed",
            "usage": {"input_tokens": 1, "cached_input_tokens": 0,
                      "cache_write_input_tokens": 0, "output_tokens": 1,
                      "reasoning_output_tokens": 0},
        })
        self.assertIn("terminal_usage_count", paired_codex.parse_jsonl(duplicate).incomplete_reasons)
        invalid = OBSERVED_JSONL.replace('"input_tokens": 20', '"input_tokens": -1')
        self.assertIn("invalid_token_usage", paired_codex.parse_jsonl(invalid).incomplete_reasons)

    def test_unknown_top_level_event_type_is_incomplete(self):
        changed = OBSERVED_JSONL + "\n" + json.dumps({"type": "item.updated", "item": {}})
        self.assertIn("unknown_event_type", paired_codex.parse_jsonl(changed).incomplete_reasons)

    def test_unexpected_top_level_field_is_incomplete(self):
        changed = OBSERVED_JSONL.replace(
            '"item": {"id": "redacted"',
            '"new_schema_field": true, "item": {"id": "redacted"',
        )
        self.assertIn("unexpected_telemetry_shape", paired_codex.parse_jsonl(changed).incomplete_reasons)

    def test_model_authored_json_is_not_telemetry(self):
        forged = OBSERVED_JSONL.replace(
            '"text": "REDACTED"',
            '"text": "{\\"actual_model\\":\\"forged\\",\\"input_tokens\\":1}"',
        )
        result = paired_codex.parse_jsonl(forged)
        self.assertIsNone(result.actual_model)
        self.assertEqual(20, result.input_tokens)

    def test_unknown_cli_version_and_adapter_fingerprint_are_incomplete(self):
        observation = paired_codex.observe_invocation(
            OBSERVED_JSONL,
            cli_version="codex-cli 0.148.0",
            expected_adapter_fingerprint="0" * 64,
        )
        self.assertIn("cli_version_mismatch", observation.incomplete_reasons)
        self.assertIn("adapter_fingerprint_mismatch", observation.incomplete_reasons)

    def test_sequential_arm_uses_frozen_lead_settings_and_hash_only_receipt(self):
        requests = []
        visible_repositories = []
        case = paired_codex.load_case_definition(paired_codex.CASE_ROOT / "small")
        snapshot = real_case_snapshot(case)
        findings = [{
            "file": "subject/percentage.py",
            "start_line": 2,
            "end_line": 2,
            "category": "correctness",
            "severity": "medium",
            "summary": "FINAL_RESPONSE_SENTINEL",
        }]
        with tempfile.TemporaryDirectory() as directory:
            state_root = Path(directory)
            def execute(request):
                requests.append(request)
                visible_repositories.append(sorted(
                    path.relative_to(request.cwd).as_posix()
                    for path in Path(request.cwd).rglob("*")
                    if path.is_file() and ".git" not in path.parts
                ))
                return completed_result(findings)

            record = paired_codex.run_sequential_arm(
                case,
                paired_codex.ScheduleEntry(0, "small", 1, "sequential"),
                fake_routing_config(),
                fake_run_contract(),
                snapshot,
                fake_execution_plan(case, "sequential"),
                seed=41,
                state_root=state_root,
                execute=execute,
                capability=fake_capability,
            )
            paired_codex.audit_proof_receipt(
                state_root, record.invocations[0].receipt, record.invocations[0].output_hash
            )
        self.assertEqual(("gpt-5.6-sol", "high"), (
            requests[0].model, requests[0].reasoning_effort
        ))
        self.assertFalse(requests[0].allow_fallback)
        self.assertFalse(requests[0].write_access)
        self.assertEqual([list(case.copy_manifest)], visible_repositories)
        self.assertTrue(record.score and record.score.accepted)
        self.assertIn("actual_model_unavailable", record.incomplete_reasons)
        serialized = json.dumps(asdict(record), sort_keys=True)
        self.assertNotIn("RAW_THREAD_SENTINEL", serialized)
        self.assertNotIn("FINAL_RESPONSE_SENTINEL", serialized)

    def test_canopy_arm_routes_leaf_and_reviewer_with_fresh_receipts(self):
        requests = []
        case = paired_codex.load_case_definition(paired_codex.CASE_ROOT / "small")
        snapshot = real_case_snapshot(case)
        findings = [{
            "file": "subject/percentage.py",
            "start_line": 2,
            "end_line": 2,
            "category": "correctness",
            "severity": "medium",
            "summary": "zero denominator",
        }]
        with tempfile.TemporaryDirectory() as directory:
            state_root = Path(directory)
            record = paired_codex.run_canopy_arm(
                case,
                paired_codex.ScheduleEntry(1, "small", 1, "canopy"),
                fake_routing_config(),
                fake_run_contract(),
                snapshot,
                fake_execution_plan(case, "canopy"),
                seed=41,
                state_root=state_root,
                execute=lambda request: requests.append(request) or completed_result(findings),
                capability=fake_capability,
            )
            for invocation in record.invocations:
                paired_codex.audit_proof_receipt(
                    state_root, invocation.receipt, invocation.output_hash
                )
        self.assertEqual(["gpt-5.6-luna", "gpt-5.6-terra"], [
            request.model for request in requests
        ])
        self.assertEqual(2, record.executed_nodes)
        self.assertEqual(2, len({invocation.receipt for invocation in record.invocations}))
        self.assertTrue(record.score and record.score.accepted)
        self.assertNotIn("RAW_THREAD_SENTINEL", requests[-1].prompt)
        self.assertIn('"summary"', requests[-1].prompt)
        self.assertNotIn('"description"', requests[-1].prompt)
        self.assertNotEqual(requests[0].cwd, requests[-1].cwd)
        self.assertTrue(all(not request.allow_fallback and not request.write_access for request in requests))

    def test_failed_leaf_has_one_auditable_receipt_and_remains_incomplete(self):
        calls = []
        case = paired_codex.load_case_definition(paired_codex.CASE_ROOT / "small")
        failed = ProviderResult("failed", "codex", "codex", False, 7, "RAW_FAILURE", "boom", {})
        with tempfile.TemporaryDirectory() as directory:
            state_root = Path(directory)
            record = paired_codex.run_canopy_arm(
                case,
                paired_codex.ScheduleEntry(1, "small", 1, "canopy"),
                fake_routing_config(),
                fake_run_contract(),
                real_case_snapshot(case),
                fake_execution_plan(case, "canopy"),
                seed=41,
                state_root=state_root,
                execute=lambda request: calls.append(request) or failed,
                capability=fake_capability,
            )
            invocation = record.invocations[0]
            paired_codex.audit_proof_receipt(state_root, invocation.receipt, invocation.output_hash)
        self.assertEqual(1, len(calls))
        self.assertEqual("failed", invocation.status)
        self.assertEqual(1, record.failed_nodes)
        self.assertEqual("incomplete", record.completion_state)
        self.assertIn("provider_failed", record.incomplete_reasons)

    def test_malformed_leaf_and_output_limit_fail_closed_without_reviewer(self):
        case = paired_codex.load_case_definition(paired_codex.CASE_ROOT / "small")
        malformed_output = OBSERVED_JSONL.replace(
            '"text": "REDACTED"', '"text": "not-json"'
        )
        malformed = ProviderResult(
            "completed", "codex", "codex", False, 0, malformed_output, None, {}
        )
        limited = ProviderResult(
            "failed", "codex", "codex", False, 125, "partial",
            "provider output exceeded 1048576 bytes", {},
        )
        for result, reason in ((malformed, "invalid_model_findings"), (limited, "provider_output_limit")):
            calls = []
            with self.subTest(reason=reason), tempfile.TemporaryDirectory() as directory:
                record = paired_codex.run_canopy_arm(
                    case,
                    paired_codex.ScheduleEntry(1, "small", 1, "canopy"),
                    fake_routing_config(),
                    fake_run_contract(),
                    real_case_snapshot(case),
                    fake_execution_plan(case, "canopy"),
                    seed=41,
                    state_root=Path(directory),
                    execute=lambda request: calls.append(request) or result,
                    capability=fake_capability,
                )
            self.assertEqual(1, len(calls))
            self.assertIn(reason, record.incomplete_reasons)
            self.assertIsNone(record.score)

    def test_leaf_finding_outside_assigned_scope_skips_reviewer(self):
        requests = []
        case = paired_codex.load_case_definition(paired_codex.CASE_ROOT / "medium")
        cross_scope = [{
            "file": "subject/retry.py",
            "start_line": 1,
            "end_line": 2,
            "category": "correctness",
            "severity": "medium",
            "summary": "belongs to the other leaf",
        }]
        own_scope = [{
            "file": "subject/retry.py",
            "start_line": 1,
            "end_line": 2,
            "category": "correctness",
            "severity": "medium",
            "summary": "zero retries skips the first attempt",
        }]
        results = iter((completed_result(cross_scope), completed_result(own_scope)))
        with tempfile.TemporaryDirectory() as directory:
            record = paired_codex.run_canopy_arm(
                case,
                paired_codex.ScheduleEntry(1, "medium", 1, "canopy"),
                fake_routing_config(),
                fake_run_contract(),
                real_case_snapshot(case),
                fake_execution_plan(case, "canopy"),
                seed=41,
                state_root=Path(directory),
                execute=lambda request: requests.append(request) or next(results),
                capability=fake_capability,
            )
        self.assertEqual(2, len(requests))
        self.assertIsNone(record.score)
        self.assertIn("leaf_scope_violation", record.incomplete_reasons)
        self.assertEqual(1, record.pruned_nodes)

    def test_incomplete_leaf_telemetry_with_valid_findings_skips_reviewer(self):
        case = paired_codex.load_case_definition(paired_codex.CASE_ROOT / "small")
        finding = [{
            "file": "subject/percentage.py",
            "start_line": 2,
            "end_line": 2,
            "category": "correctness",
            "severity": "medium",
            "summary": "zero denominator",
        }]
        completed = completed_result(finding)
        for suffix, reason in (
            ("not-json", "malformed_jsonl"),
            (json.dumps({"type": "item.updated", "item": {}}), "unknown_event_type"),
        ):
            requests = []
            incomplete = replace(completed, output=completed.output + "\n" + suffix)
            with self.subTest(reason=reason), tempfile.TemporaryDirectory() as directory:
                record = paired_codex.run_canopy_arm(
                    case,
                    paired_codex.ScheduleEntry(1, "small", 1, "canopy"),
                    fake_routing_config(),
                    fake_run_contract(),
                    real_case_snapshot(case),
                    fake_execution_plan(case, "canopy"),
                    seed=41,
                    state_root=Path(directory),
                    execute=lambda request: requests.append(request) or incomplete,
                    capability=fake_capability,
                )
            self.assertEqual(1, len(requests))
            self.assertIsNone(record.score)
            self.assertIn(reason, record.incomplete_reasons)
            self.assertEqual(1, record.pruned_nodes)

    def test_reviewer_aggregate_and_fully_dispatched_prompt_have_exact_bounds(self):
        self.assertEqual("x" * 24_000, paired_codex._bounded_reviewer_aggregate("x" * 24_000))
        with self.assertRaisesRegex(ValueError, "reviewer_aggregate_limit"):
            paired_codex._bounded_reviewer_aggregate("x" * 24_001)
        empty = paired_codex._reviewer_prompt("")
        exact_aggregate = "x" * (
            paired_codex.MAX_PROMPT_CHARS
            - len(paired_codex.SECURITY_PREAMBLE)
            - len(empty)
        )
        exact = paired_codex._reviewer_prompt(exact_aggregate)
        self.assertEqual(
            paired_codex.MAX_PROMPT_CHARS,
            len(paired_codex.SECURITY_PREAMBLE + exact),
        )
        with self.assertRaisesRegex(ValueError, "reviewer_prompt_limit"):
            paired_codex._reviewer_prompt(exact_aggregate + "x")

    def test_reviewer_aggregate_overflow_stops_before_reviewer_dispatch(self):
        requests = []
        case = paired_codex.load_case_definition(paired_codex.CASE_ROOT / "small")
        finding = [{
            "file": "subject/percentage.py", "start_line": 2, "end_line": 2,
            "category": "correctness", "severity": "medium", "summary": "found",
        }]
        with tempfile.TemporaryDirectory() as directory, patch.object(
            paired_codex, "_aggregate_leaf_artifacts", return_value="x" * 24_001
        ):
            record = paired_codex.run_canopy_arm(
                case,
                paired_codex.ScheduleEntry(1, "small", 1, "canopy"),
                fake_routing_config(),
                fake_run_contract(),
                real_case_snapshot(case),
                fake_execution_plan(case, "canopy"),
                seed=41,
                state_root=Path(directory),
                execute=lambda request: requests.append(request) or completed_result(finding),
                capability=fake_capability,
            )
        self.assertEqual(1, len(requests))
        self.assertIn("reviewer_aggregate_limit", record.incomplete_reasons)

    def test_keyboard_interrupt_is_flushed_as_evidence_then_reraised(self):
        case = paired_codex.load_case_definition(paired_codex.CASE_ROOT / "small")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            results = root / "results.jsonl"
            with self.assertRaises(KeyboardInterrupt):
                paired_codex.run_sequential_arm(
                    case,
                    paired_codex.ScheduleEntry(0, "small", 1, "sequential"),
                    fake_routing_config(),
                    fake_run_contract(),
                    real_case_snapshot(case),
                    fake_execution_plan(case, "sequential"),
                    seed=41,
                    state_root=root,
                    results_path=results,
                    execute=lambda _request: (_ for _ in ()).throw(KeyboardInterrupt()),
                    capability=fake_capability,
                )
            row = json.loads(results.read_text(encoding="utf-8"))
        self.assertEqual("arm-result", row["kind"])
        self.assertEqual("interrupted", row["completion_state"])
        self.assertIn("interrupted", row["incomplete_reasons"])

    def test_leaf_receipt_interrupt_keeps_only_auditable_prefix_and_reraises(self):
        case = paired_codex.load_case_definition(paired_codex.CASE_ROOT / "medium")
        snapshot = real_case_snapshot(case)
        config = fake_routing_config()
        definitions = fake_case_definitions()
        schedule = paired_codex.build_schedule(
            41,
            fake_run_contract(),
            (fake_case_snapshots()[0], snapshot, fake_case_snapshots()[2]),
            definitions,
            config,
        )
        entry = next(
            item for item in schedule.entries
            if (item.case_id, item.repetition, item.arm) == ("medium", 1, "canopy")
        )
        plan = next(
            item for item in schedule.execution_plans
            if (item.case_id, item.arm) == ("medium", "canopy")
        )
        findings = iter((
            [{
                "file": "subject/archive.py", "start_line": 5, "end_line": 7,
                "category": "security", "severity": "high", "summary": "escape",
            }],
            [{
                "file": "subject/retry.py", "start_line": 1, "end_line": 2,
                "category": "correctness", "severity": "medium", "summary": "retry",
            }],
        ))
        original_append = runtime_tree.append_proof_receipt
        writes = []

        def interrupt_second_receipt(*args, **kwargs):
            writes.append(args[0])
            if len(writes) == 2:
                raise KeyboardInterrupt()
            return original_append(*args, **kwargs)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            results = root / "results.jsonl"
            paired_codex.append_result_record(
                results, {"kind": "schedule", **asdict(schedule)}
            )
            with patch.object(
                runtime_tree,
                "append_proof_receipt",
                side_effect=interrupt_second_receipt,
            ), self.assertRaises(KeyboardInterrupt):
                paired_codex.run_canopy_arm(
                    case, entry, config, fake_run_contract(), snapshot, plan,
                    seed=41,
                    state_root=root,
                    results_path=results,
                    execute=lambda _request: completed_result(next(findings)),
                    capability=fake_capability,
                )
            _, records = paired_codex.load_results(results)
            record = records[0]
            self.assertEqual(("archive",), tuple(
                invocation.node_id for invocation in record.invocations
            ))
            paired_codex.audit_proof_receipt(
                root, record.invocations[0].receipt, record.invocations[0].output_hash
            )
            missing = root / "receipts" / paired_codex._schedule_slug(entry) / "retry.jsonl"
            self.assertFalse(missing.exists())
        self.assertEqual("interrupted", record.completion_state)
        self.assertIn("interrupted", record.incomplete_reasons)

    def test_probe_without_execute_never_calls_provider(self):
        output = io.StringIO()
        with patch.object(paired_codex, "execute_provider") as execute, redirect_stdout(output):
            status = paired_codex.main(["probe"])
        self.assertEqual(0, status)
        self.assertIn('"execute": false', output.getvalue().lower())
        execute.assert_not_called()

    def test_direct_probe_is_dry_run(self):
        completed = subprocess.run(
            [sys.executable, str(Path(__file__).parents[1] / "benchmarks" / "paired_codex.py"), "probe"],
            capture_output=True,
            check=False,
            text=True,
        )
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertFalse(json.loads(completed.stdout)["execute"])
