#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SPEC = importlib.util.spec_from_file_location(
    "home_manager_workflow_guards", HERE / "verify-workflow-guards.py"
)
assert SPEC is not None and SPEC.loader is not None
guards = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(guards)

WORKFLOWS = (
    "backport.yml",
    "conflicts.yml",
    "github_pages.yml",
    "labeler.yml",
    "tag-maintainers.yml",
    "test.yml",
    "update-maintainers.yml",
    "validate-maintainers.yml",
)
FORK_PATH = ROOT / ".github" / "workflows" / guards.FORK_WORKFLOW
ARCHIVE_ROOT = HERE / "workflow-archive" / "files" / ".github" / "workflows"


def fork_workflow() -> str:
    return FORK_PATH.read_text(encoding="utf-8")


def replace_once(text: str, old: str, new: str) -> str:
    if text.count(old) < 1:
        raise AssertionError(f"fixture fragment is missing: {old!r}")
    return text.replace(old, new, 1)


def workflow(condition: str) -> str:
    return f"""name: fixture
on: push
jobs:
  first:
    if: {condition}
    runs-on: ubuntu-24.04
    steps: []
"""


def workflow_with_steps(steps: str) -> str:
    return workflow(guards.OWNER_GUARD).replace("    steps: []", steps)


class WorkflowGuardTests(unittest.TestCase):
    def test_every_executable_workflow_passes_the_firewall(self) -> None:
        paths = guards.verify_repository(ROOT)
        self.assertEqual(paths, [FORK_PATH])

    def test_only_axiomlayer_workflow_remains_active(self) -> None:
        active_names = {
            path.name for path in (ROOT / ".github" / "workflows").iterdir()
        }
        self.assertEqual(active_names, {guards.FORK_WORKFLOW})

    def test_every_inherited_workflow_is_inert_and_archived(self) -> None:
        for name in WORKFLOWS:
            with self.subTest(name=name):
                self.assertFalse((ROOT / ".github" / "workflows" / name).exists())
                archive = ARCHIVE_ROOT / name
                self.assertTrue(archive.is_file())
                self.assertFalse(archive.is_symlink())

    def test_fork_workflow_passes_the_hosted_daily_schedule_policy(self) -> None:
        guards.verify_fork_workflow(fork_workflow(), str(FORK_PATH))

    def test_canonical_fork_identity_is_exact_in_machine_evidence(self) -> None:
        policy = json.loads((HERE / "policy.json").read_text(encoding="utf-8"))
        lock = json.loads((HERE / "flake.lock").read_text(encoding="utf-8"))
        flake = (HERE / "flake.nix").read_text(encoding="utf-8")
        workflow_text = fork_workflow()
        home_manager_lock = lock["nodes"]["home-manager"]

        self.assertEqual(policy["source"]["repository"], guards.FORK_REPOSITORY)
        self.assertEqual(
            f"refs/heads/{policy['source']['defaultBranch']}",
            guards.FORK_DEFAULT_REF,
        )
        self.assertEqual(home_manager_lock["locked"]["owner"], "axiomlayer")
        self.assertEqual(home_manager_lock["original"]["owner"], "axiomlayer")
        self.assertIn(f"github:{guards.FORK_REPOSITORY}/", flake)
        self.assertIn(f'source = "{guards.FORK_REPOSITORY}";', flake)
        self.assertEqual(workflow_text.count(guards.FORK_SOURCE_EVIDENCE), 1)

        noncanonical = "Axiom" + "Layer/home-manager"
        for machine_text in (
            json.dumps(policy),
            json.dumps(lock),
            flake,
            workflow_text,
        ):
            self.assertNotIn(noncanonical, machine_text)

    def test_noncanonical_activation_evidence_is_refused(self) -> None:
        noncanonical = "Axiom" + "Layer/home-manager"
        text = replace_once(
            fork_workflow(), guards.FORK_SOURCE_EVIDENCE, f'.source == "{noncanonical}"'
        )
        with self.assertRaisesRegex(guards.GuardError, "canonical fork identity"):
            guards.verify_fork_workflow(text)

    def test_fork_extra_trigger_is_refused(self) -> None:
        text = replace_once(
            fork_workflow(),
            "  workflow_dispatch:\n",
            "  workflow_dispatch:\n  push:\n",
        )
        with self.assertRaisesRegex(guards.GuardError, "only one schedule"):
            guards.verify_fork_workflow(text)

    def test_fork_missing_schedule_is_refused(self) -> None:
        text = replace_once(
            fork_workflow(),
            f'  schedule:\n    - cron: "{guards.FORK_CRON}"\n',
            "",
        )
        with self.assertRaisesRegex(guards.GuardError, "only one schedule"):
            guards.verify_fork_workflow(text)

    def test_fork_weekly_only_cadence_is_refused(self) -> None:
        text = replace_once(
            fork_workflow(),
            f'    - cron: "{guards.FORK_CRON}"',
            '    - cron: "17 5 * * 1"',
        )
        with self.assertRaisesRegex(guards.GuardError, "daily cadence"):
            guards.verify_fork_workflow(text)

    def test_fork_manual_inputs_are_refused(self) -> None:
        text = replace_once(
            fork_workflow(),
            "  workflow_dispatch:\n",
            "  workflow_dispatch:\n    inputs:\n      target:\n        required: false\n",
        )
        with self.assertRaisesRegex(guards.GuardError, "input-free manual"):
            guards.verify_fork_workflow(text)

    def test_fork_wrong_repository_is_refused(self) -> None:
        text = fork_workflow().replace(
            "github.repository == 'axiomlayer/home-manager'",
            "github.repository == 'example/home-manager'",
        )
        with self.assertRaisesRegex(guards.GuardError, "guard must match exactly"):
            guards.verify_fork_workflow(text)

    def test_fork_wrong_default_ref_is_refused(self) -> None:
        text = fork_workflow().replace(
            "github.ref == 'refs/heads/master'",
            "github.ref == 'refs/heads/topic'",
        )
        with self.assertRaisesRegex(guards.GuardError, "guard must match exactly"):
            guards.verify_fork_workflow(text)

    def test_fork_unprotected_ref_is_refused(self) -> None:
        text = fork_workflow().replace(
            "github.ref_protected == true", "github.ref_protected == false"
        )
        with self.assertRaisesRegex(guards.GuardError, "guard must match exactly"):
            guards.verify_fork_workflow(text)

    def test_fork_wrong_workflow_ref_is_refused(self) -> None:
        text = fork_workflow().replace(
            guards.FORK_EXACT_WORKFLOW_REF,
            "axiomlayer/home-manager/.github/workflows/other.yml@refs/heads/master",
        )
        with self.assertRaisesRegex(guards.GuardError, "guard must match exactly"):
            guards.verify_fork_workflow(text)

    def test_fork_unreviewed_event_guard_is_refused(self) -> None:
        text = fork_workflow().replace(
            "|| github.event_name == 'workflow_dispatch')",
            "|| github.event_name == 'push')",
        )
        with self.assertRaisesRegex(guards.GuardError, "guard must match exactly"):
            guards.verify_fork_workflow(text)

    def test_fork_missing_job_guard_is_refused(self) -> None:
        text = replace_once(
            fork_workflow(),
            "    if: >-\n"
            "      github.repository == 'axiomlayer/home-manager'\n"
            "      && github.ref == 'refs/heads/master'\n"
            "      && github.ref_protected == true\n"
            "      && github.workflow_ref == 'axiomlayer/home-manager/.github/workflows/axiomlayer-integration.yml@refs/heads/master'\n"
            "      && (github.event_name == 'schedule'\n"
            "      || github.event_name == 'workflow_dispatch')\n",
            "",
        )
        with self.assertRaisesRegex(guards.GuardError, "exactly one job-level if"):
            guards.verify_fork_workflow(text)

    def test_fork_self_hosted_job_is_refused(self) -> None:
        text = replace_once(
            fork_workflow(),
            "    runs-on: ubuntu-24.04",
            "    runs-on: self-hosted",
        )
        with self.assertRaisesRegex(guards.GuardError, "reviewed hosted label"):
            guards.verify_fork_workflow(text)

    def test_fork_runner_group_is_refused(self) -> None:
        text = replace_once(
            fork_workflow(),
            "    runs-on: ubuntu-24.04",
            "    runs-on:\n      group: fleet-linux\n      labels: ubuntu-24.04",
        )
        with self.assertRaisesRegex(guards.GuardError, "reviewed hosted label"):
            guards.verify_fork_workflow(text)

    def test_fork_self_hosted_matrix_entry_is_refused(self) -> None:
        text = replace_once(
            fork_workflow(),
            "            runner: ubuntu-24.04-arm",
            "            runner: self-hosted",
        )
        with self.assertRaisesRegex(guards.GuardError, "reviewed hosted set"):
            guards.verify_fork_workflow(text)

    def test_fork_write_permission_is_refused(self) -> None:
        text = replace_once(fork_workflow(), "  contents: read", "  contents: write")
        with self.assertRaisesRegex(guards.GuardError, "contents-read-only"):
            guards.verify_fork_workflow(text)

    def test_fork_job_permission_override_is_refused(self) -> None:
        text = replace_once(
            fork_workflow(),
            "    runs-on: ubuntu-24.04",
            "    permissions:\n      contents: write\n    runs-on: ubuntu-24.04",
        )
        with self.assertRaisesRegex(guards.GuardError, "workflow scope"):
            guards.verify_fork_workflow(text)

    def test_fork_secret_reference_is_refused(self) -> None:
        text = replace_once(
            fork_workflow(),
            "        run: integration/axiomlayer/test-policy.sh",
            "        env:\n"
            "          SERVICE_TOKEN: ${{ secrets.SERVICE_TOKEN }}\n"
            "        run: integration/axiomlayer/test-policy.sh",
        )
        with self.assertRaisesRegex(guards.GuardError, "credential or secret"):
            guards.verify_fork_workflow(text)

    def test_fork_credential_variable_is_refused(self) -> None:
        text = replace_once(
            fork_workflow(),
            "        run: integration/axiomlayer/test-policy.sh",
            "        env:\n"
            "          GITHUB_TOKEN: unavailable\n"
            "        run: integration/axiomlayer/test-policy.sh",
        )
        with self.assertRaisesRegex(guards.GuardError, "credential or secret"):
            guards.verify_fork_workflow(text)

    def test_fork_mutable_action_is_refused(self) -> None:
        text = replace_once(
            fork_workflow(),
            "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1",
            "actions/checkout@main",
        )
        with self.assertRaisesRegex(guards.GuardError, "full commit SHA"):
            guards.verify_fork_workflow(text)

    def test_fork_extra_pinned_action_is_refused(self) -> None:
        text = replace_once(
            fork_workflow(),
            "    steps:\n",
            "    steps:\n"
            "      - uses: example/build-action@0000000000000000000000000000000000000000\n",
        )
        with self.assertRaisesRegex(guards.GuardError, "action inventory"):
            guards.verify_fork_workflow(text)

    def test_fork_checkout_source_override_is_refused(self) -> None:
        text = replace_once(
            fork_workflow(),
            "          persist-credentials: false\n",
            "          persist-credentials: false\n"
            "          repository: nix-community/home-manager\n",
        )
        with self.assertRaisesRegex(guards.GuardError, "may not override source"):
            guards.verify_fork_workflow(text)

    def test_fork_non_clean_checkout_is_refused(self) -> None:
        text = replace_once(
            fork_workflow(), "          clean: true", "          clean: false"
        )
        with self.assertRaisesRegex(guards.GuardError, "clean: true"):
            guards.verify_fork_workflow(text)

    def test_fork_repository_sync_is_refused(self) -> None:
        text = replace_once(
            fork_workflow(),
            "        run: integration/axiomlayer/test-policy.sh",
            "        run: git fetch upstream",
        )
        with self.assertRaisesRegex(guards.GuardError, "synchronization"):
            guards.verify_fork_workflow(text)

    def test_fork_external_write_is_refused(self) -> None:
        text = replace_once(
            fork_workflow(),
            "        run: integration/axiomlayer/test-policy.sh",
            "        run: git push origin HEAD",
        )
        with self.assertRaisesRegex(guards.GuardError, "synchronization"):
            guards.verify_fork_workflow(text)

    def test_fork_publish_release_and_deploy_surfaces_are_refused(self) -> None:
        mutations = (
            "        run: npm publish",
            "        run: release create scheduled",
            "        environment: production\n"
            "        run: integration/axiomlayer/test-policy.sh",
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                text = replace_once(
                    fork_workflow(),
                    "        run: integration/axiomlayer/test-policy.sh",
                    mutation,
                )
                with self.assertRaises(guards.GuardError):
                    guards.verify_fork_workflow(text)

    def test_fork_container_image_is_refused(self) -> None:
        text = replace_once(
            fork_workflow(),
            "    runs-on: ubuntu-24.04",
            "    container: ubuntu:latest\n    runs-on: ubuntu-24.04",
        )
        with self.assertRaisesRegex(guards.GuardError, "container image"):
            guards.verify_fork_workflow(text)

    def test_fork_direct_network_tooling_is_refused(self) -> None:
        text = replace_once(
            fork_workflow(),
            "        run: integration/axiomlayer/test-policy.sh",
            "        run: curl --request POST https://example.invalid",
        )
        with self.assertRaisesRegex(guards.GuardError, "external network"):
            guards.verify_fork_workflow(text)

    def test_fork_fail_open_step_is_refused(self) -> None:
        text = replace_once(
            fork_workflow(),
            "        run: integration/axiomlayer/test-policy.sh",
            "        continue-on-error: true\n"
            "        run: integration/axiomlayer/test-policy.sh",
        )
        with self.assertRaisesRegex(guards.GuardError, "fail-open"):
            guards.verify_fork_workflow(text)

    def test_missing_guard_is_refused(self) -> None:
        with self.assertRaisesRegex(guards.GuardError, "mandatory first conjunct"):
            guards.verify_text(workflow("success()"))

    def test_comment_only_guard_is_refused(self) -> None:
        with self.assertRaisesRegex(guards.GuardError, "mandatory first conjunct"):
            guards.verify_text(workflow("success() # " + guards.OWNER_GUARD))

    def test_top_level_or_bypass_is_refused(self) -> None:
        with self.assertRaisesRegex(guards.GuardError, "top-level OR"):
            guards.verify_text(workflow(guards.OWNER_GUARD + " || success()"))

    def test_guarded_nested_or_is_allowed(self) -> None:
        guards.verify_text(
            workflow(guards.OWNER_GUARD + " && (success() || failure())")
        )

    def test_guard_after_another_condition_is_refused(self) -> None:
        with self.assertRaisesRegex(guards.GuardError, "mandatory first conjunct"):
            guards.verify_text(workflow("success() && " + guards.OWNER_GUARD))

    def test_duplicate_if_is_refused(self) -> None:
        text = workflow(guards.OWNER_GUARD).replace(
            "    runs-on:", "    if: success()\n    runs-on:"
        )
        with self.assertRaisesRegex(guards.GuardError, "exactly one"):
            guards.verify_text(text)

    def test_inline_job_is_refused(self) -> None:
        text = "name: fixture\non: push\njobs:\n  first: {runs-on: ubuntu-24.04}\n"
        with self.assertRaisesRegex(guards.GuardError, "inline or malformed"):
            guards.verify_text(text)

    def test_cachix_bootstrap_is_refused_in_an_executable_workflow(self) -> None:
        text = workflow_with_steps(
            """    steps:
      - uses: cachix/install-nix-action@0000000000000000000000000000000000000000
"""
        )
        with self.assertRaisesRegex(guards.GuardError, "delegated Nix bootstrap"):
            guards.verify_workflow_safety(text)

    def test_cachix_cache_action_is_refused_in_an_executable_workflow(self) -> None:
        text = workflow_with_steps(
            """    steps:
      - uses: cachix/cachix-action@0000000000000000000000000000000000000000
"""
        )
        with self.assertRaisesRegex(guards.GuardError, "delegated Nix bootstrap"):
            guards.verify_workflow_safety(text)

    def test_determinate_bootstrap_is_refused_in_an_executable_workflow(self) -> None:
        text = workflow_with_steps(
            """    steps:
      - uses: DeterminateSystems/nix-installer-action@0000000000000000000000000000000000000000
"""
        )
        with self.assertRaisesRegex(guards.GuardError, "delegated Nix bootstrap"):
            guards.verify_workflow_safety(text)

    def test_checkout_without_nonpersistence_is_refused(self) -> None:
        text = workflow_with_steps(
            """    steps:
      - uses: actions/checkout@0000000000000000000000000000000000000000
"""
        )
        with self.assertRaisesRegex(guards.GuardError, "persist-credentials"):
            guards.verify_workflow_safety(text)

    def test_checkout_with_persistence_is_refused(self) -> None:
        text = workflow_with_steps(
            """    steps:
      - uses: actions/checkout@0000000000000000000000000000000000000000
        with:
          persist-credentials: true
"""
        )
        with self.assertRaisesRegex(guards.GuardError, "persist-credentials"):
            guards.verify_workflow_safety(text)

    def test_checkout_with_nonpersistence_is_allowed(self) -> None:
        text = workflow_with_steps(
            """    steps:
      - uses: actions/checkout@0000000000000000000000000000000000000000
        with:
          persist-credentials: false
"""
        )
        guards.verify_workflow_safety(text)

    def test_credential_in_local_wrapper_step_is_refused(self) -> None:
        text = workflow_with_steps(
            f"""    steps:
      - name: Install Nix
        env:
          GITHUB_TOKEN: ${{{{ github.token }}}}
        run: {guards.LOCAL_NIX_WRAPPER}
"""
        )
        with self.assertRaisesRegex(guards.GuardError, "credential is routed"):
            guards.verify_workflow_safety(text)

    def test_inert_archive_fixture_is_outside_the_executable_scan(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            active = root / ".github" / "workflows" / guards.FORK_WORKFLOW
            active.parent.mkdir(parents=True)
            active.write_text(fork_workflow(), encoding="utf-8")
            archive = root / "integration" / "axiomlayer" / "upstream-workflows"
            archive.mkdir(parents=True)
            (archive / "old.yml").write_text(
                "uses: cachix/install-nix-action@archive-fixture\n",
                encoding="utf-8",
            )
            self.assertEqual(guards.verify_repository(root), [active])


if __name__ == "__main__":
    unittest.main()
