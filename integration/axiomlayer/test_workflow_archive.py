#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Any, Callable

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SPEC = importlib.util.spec_from_file_location(
    "home_manager_workflow_archive", HERE / "verify-workflow-archive.py"
)
assert SPEC is not None and SPEC.loader is not None
archive = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(archive)

INVENTORY = Path(archive.INVENTORY_PATH)
ARCHIVE_ROOT = Path(archive.ARCHIVE_ROOT)
ACTIVE_WORKFLOW = Path(archive.ACTIVE_WORKFLOW)
EXPECTED_SOURCES = {
    ".github/dependabot.yml",
    ".github/labeler.yml",
    ".github/workflows/backport.yml",
    ".github/workflows/conflicts.yml",
    ".github/workflows/github_pages.yml",
    ".github/workflows/labeler.yml",
    ".github/workflows/tag-maintainers.yml",
    ".github/workflows/test.yml",
    ".github/workflows/update-maintainers.yml",
    ".github/workflows/validate-maintainers.yml",
}


def fixture(root: Path) -> None:
    active_parent = (root / ACTIVE_WORKFLOW).parent
    active_parent.mkdir(parents=True)
    shutil.copy2(ROOT / ACTIVE_WORKFLOW, root / ACTIVE_WORKFLOW)
    archive_parent = (root / ARCHIVE_ROOT).parent
    archive_parent.mkdir(parents=True)
    shutil.copytree(ROOT / ARCHIVE_ROOT, root / ARCHIVE_ROOT)
    shutil.copy2(ROOT / INVENTORY, root / INVENTORY)


def inventory(root: Path) -> dict[str, Any]:
    return json.loads((root / INVENTORY).read_text(encoding="utf-8"))


def mutate_inventory(root: Path, mutation: Callable[[dict[str, Any]], None]) -> None:
    document = inventory(root)
    mutation(document)
    (root / INVENTORY).write_text(
        json.dumps(document, indent=2) + "\n", encoding="utf-8"
    )


class WorkflowArchiveTests(unittest.TestCase):
    def verify_fixture(self, root: Path) -> list[Path]:
        return archive.verify_repository(root, baseline_repository=ROOT)

    def test_real_archive_matches_every_baseline_blob(self) -> None:
        verified = archive.verify_repository(ROOT)
        self.assertEqual(len(verified), 10)

    def test_inventory_names_the_full_baseline_and_active_identity(self) -> None:
        document = inventory(ROOT)
        self.assertEqual(document["baseline"]["commit"], archive.BASELINE_COMMIT)
        self.assertEqual(
            document["baseline"]["workflowTree"], archive.BASELINE_WORKFLOW_TREE
        )
        self.assertEqual(
            document["baseline"]["supportPaths"], list(archive.SUPPORT_PATHS)
        )
        self.assertEqual(document["activeWorkflow"], archive.ACTIVE_WORKFLOW)
        self.assertEqual(
            {entry["sourcePath"] for entry in document["files"]},
            EXPECTED_SOURCES,
        )

    def test_missing_archive_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            fixture(root)
            (root / ARCHIVE_ROOT / ".github/workflows/backport.yml").unlink()
            with self.assertRaisesRegex(
                archive.ArchiveError, "missing, extra, or renamed"
            ):
                self.verify_fixture(root)

    def test_extra_archive_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            fixture(root)
            (root / ARCHIVE_ROOT / ".github/workflows/extra.yml").write_text(
                "name: unexpected\n", encoding="utf-8"
            )
            with self.assertRaisesRegex(
                archive.ArchiveError, "missing, extra, or renamed"
            ):
                self.verify_fixture(root)

    def test_renamed_archive_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            fixture(root)
            source = root / ARCHIVE_ROOT / ".github/workflows/backport.yml"
            source.rename(source.with_name("backport-renamed.yml"))
            with self.assertRaisesRegex(
                archive.ArchiveError, "missing, extra, or renamed"
            ):
                self.verify_fixture(root)

    def test_symlink_archive_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            fixture(root)
            source = root / ARCHIVE_ROOT / ".github/workflows/backport.yml"
            source.unlink()
            source.symlink_to("conflicts.yml")
            with self.assertRaisesRegex(archive.ArchiveError, "contains a symlink"):
                self.verify_fixture(root)

    def test_tampered_archive_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            fixture(root)
            source = root / ARCHIVE_ROOT / ".github/workflows/backport.yml"
            source.write_bytes(source.read_bytes() + b"# tampered\n")
            with self.assertRaisesRegex(archive.ArchiveError, "bytes differ"):
                self.verify_fixture(root)

    def test_archive_executable_bit_drift_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            fixture(root)
            source = root / ARCHIVE_ROOT / ".github/workflows/backport.yml"
            source.chmod(source.stat().st_mode | 0o111)
            with self.assertRaisesRegex(
                archive.ArchiveError, "executable mode differs"
            ):
                self.verify_fixture(root)

    def test_inventory_sha256_drift_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            fixture(root)
            mutate_inventory(
                root, lambda document: document["files"][0].update(sha256="0" * 64)
            )
            with self.assertRaisesRegex(
                archive.ArchiveError, "baseline SHA-256 mismatch"
            ):
                self.verify_fixture(root)

    def test_inventory_git_blob_drift_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            fixture(root)
            mutate_inventory(
                root, lambda document: document["files"][0].update(gitBlob="0" * 40)
            )
            with self.assertRaisesRegex(
                archive.ArchiveError, "baseline Git blob mismatch"
            ):
                self.verify_fixture(root)

    def test_inventory_byte_count_drift_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            fixture(root)
            mutate_inventory(
                root,
                lambda document: document["files"][0].update(
                    bytes=document["files"][0]["bytes"] + 1
                ),
            )
            with self.assertRaisesRegex(
                archive.ArchiveError, "baseline byte count mismatch"
            ):
                self.verify_fixture(root)

    def test_inventory_baseline_drift_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            fixture(root)
            mutate_inventory(
                root,
                lambda document: document["baseline"].update(commit="0" * 40),
            )
            with self.assertRaisesRegex(archive.ArchiveError, "baseline changed"):
                self.verify_fixture(root)

    def test_inventory_omission_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            fixture(root)
            mutate_inventory(root, lambda document: document["files"].pop())
            with self.assertRaisesRegex(archive.ArchiveError, "exactly cover"):
                self.verify_fixture(root)

    def test_inventory_source_rename_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            fixture(root)

            def rename(document: dict[str, Any]) -> None:
                entry = document["files"][-1]
                entry["sourcePath"] = ".github/workflows/zzzz-renamed.yml"
                entry["archivePath"] = f"{archive.ARCHIVE_ROOT}/{entry['sourcePath']}"

            mutate_inventory(root, rename)
            with self.assertRaisesRegex(archive.ArchiveError, "exactly cover"):
                self.verify_fixture(root)

    def test_inventory_archive_rename_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            fixture(root)
            mutate_inventory(
                root,
                lambda document: document["files"][0].update(
                    archivePath=(
                        f"{archive.ARCHIVE_ROOT}/.github/workflows/renamed.yml"
                    )
                ),
            )
            with self.assertRaisesRegex(archive.ArchiveError, "archivePath is renamed"):
                self.verify_fixture(root)

    def test_extra_active_workflow_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            fixture(root)
            (root / ACTIVE_WORKFLOW.parent / "extra.yml").write_text(
                "name: unexpected\n", encoding="utf-8"
            )
            with self.assertRaisesRegex(archive.ArchiveError, "exactly axiomlayer"):
                self.verify_fixture(root)

    def test_extra_active_support_file_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            fixture(root)
            (root / ACTIVE_WORKFLOW.parent / "helper.sh").write_text(
                "#!/bin/sh\n", encoding="utf-8"
            )
            with self.assertRaisesRegex(archive.ArchiveError, "exactly axiomlayer"):
                self.verify_fixture(root)

    def test_restored_dependabot_automation_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            fixture(root)
            source = root / ".github/dependabot.yml"
            shutil.copy2(root / ARCHIVE_ROOT / source.relative_to(root), source)
            with self.assertRaisesRegex(archive.ArchiveError, "must be quarantined"):
                self.verify_fixture(root)

    def test_restored_labeler_support_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            fixture(root)
            source = root / ".github/labeler.yml"
            shutil.copy2(root / ARCHIVE_ROOT / source.relative_to(root), source)
            with self.assertRaisesRegex(archive.ArchiveError, "must be quarantined"):
                self.verify_fixture(root)

    def test_missing_active_workflow_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            fixture(root)
            (root / ACTIVE_WORKFLOW).unlink()
            with self.assertRaisesRegex(archive.ArchiveError, "exactly axiomlayer"):
                self.verify_fixture(root)

    def test_symlink_active_workflow_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            fixture(root)
            active = root / ACTIVE_WORKFLOW
            active.unlink()
            active.symlink_to(ROOT / ACTIVE_WORKFLOW)
            with self.assertRaisesRegex(archive.ArchiveError, "contains a symlink"):
                self.verify_fixture(root)

    def test_symlink_archive_root_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            fixture(root)
            shutil.rmtree(root / ARCHIVE_ROOT)
            (root / ARCHIVE_ROOT).symlink_to(
                ROOT / ARCHIVE_ROOT, target_is_directory=True
            )
            with self.assertRaisesRegex(archive.ArchiveError, "traverses a symlink"):
                self.verify_fixture(root)

    def test_symlink_inventory_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            fixture(root)
            path = root / INVENTORY
            path.unlink()
            path.symlink_to(ROOT / INVENTORY)
            with self.assertRaisesRegex(archive.ArchiveError, "traverses a symlink"):
                self.verify_fixture(root)

    def test_unsafe_inventory_path_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            fixture(root)
            mutate_inventory(
                root,
                lambda document: document["files"][0].update(
                    sourcePath=".github/workflows/../outside.yml"
                ),
            )
            with self.assertRaisesRegex(archive.ArchiveError, "unsafe path component"):
                self.verify_fixture(root)


if __name__ == "__main__":
    unittest.main()
