#!/usr/bin/env python3
"""Verify the byte-exact, inert archive of inherited upstream workflows."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any

BASELINE_REPOSITORY = "nix-community/home-manager"
BASELINE_COMMIT = "ec172013fa62135f58fb58dd17ae9651e8f39727"
BASELINE_WORKFLOW_TREE = "19960ee8e5e61e8108bf13a15dbbbd6932292568"
ACTIVE_WORKFLOW = ".github/workflows/axiomlayer-integration.yml"
WORKFLOW_ROOT = ".github/workflows"
SUPPORT_PATHS = (".github/dependabot.yml", ".github/labeler.yml")
ARCHIVE_ROOT = "integration/axiomlayer/workflow-archive/files"
INVENTORY_PATH = "integration/axiomlayer/workflow-archive/inventory.json"
INVENTORY_SCHEMA = "axiomlayer-inherited-workflow-archive-v1"
OBJECT_ID = re.compile(r"[0-9a-f]{40}")
SHA256 = re.compile(r"[0-9a-f]{64}")
FILE_KEYS = {
    "sourcePath",
    "archivePath",
    "sourceMode",
    "gitBlob",
    "bytes",
    "sha256",
}


class ArchiveError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ArchiveError(message)


def repository_relative_path(value: Any, label: str) -> str:
    require(isinstance(value, str), f"{label} must be a string")
    require(bool(value) and not value.startswith("/"), f"{label} must be relative")
    parts = value.split("/")
    require(
        all(part not in {"", ".", ".."} for part in parts),
        f"{label} contains an unsafe path component",
    )
    return value


def safe_path(repo_root: Path, relative: str, label: str) -> Path:
    repository_relative_path(relative, label)
    current = repo_root
    for part in relative.split("/"):
        current = current / part
        try:
            mode = current.lstat().st_mode
        except FileNotFoundError:
            break
        require(not stat.S_ISLNK(mode), f"{label} traverses a symlink: {current}")
    return current


def regular_file(
    repo_root: Path, relative: str, label: str
) -> tuple[Path, os.stat_result]:
    path = safe_path(repo_root, relative, label)
    try:
        metadata = path.lstat()
    except FileNotFoundError as error:
        raise ArchiveError(f"{label} is missing: {relative}") from error
    require(
        stat.S_ISREG(metadata.st_mode), f"{label} is not a regular file: {relative}"
    )
    return path, metadata


def regular_directory(repo_root: Path, relative: str, label: str) -> Path:
    path = safe_path(repo_root, relative, label)
    try:
        metadata = path.lstat()
    except FileNotFoundError as error:
        raise ArchiveError(f"{label} is missing: {relative}") from error
    require(stat.S_ISDIR(metadata.st_mode), f"{label} is not a directory: {relative}")
    return path


def directory_files(repo_root: Path, relative: str, label: str) -> set[str]:
    root = regular_directory(repo_root, relative, label)
    files: set[str] = set()
    pending = [root]
    while pending:
        directory = pending.pop()
        try:
            entries = list(os.scandir(directory))
        except OSError as error:
            raise ArchiveError(
                f"cannot inspect {label}: {directory}: {error}"
            ) from error
        for entry in entries:
            path = Path(entry.path)
            path_label = path.relative_to(repo_root).as_posix()
            require(not entry.is_symlink(), f"{label} contains a symlink: {path_label}")
            if entry.is_dir(follow_symlinks=False):
                pending.append(path)
            elif entry.is_file(follow_symlinks=False):
                files.add(path_label)
            else:
                raise ArchiveError(f"{label} contains a non-regular path: {path_label}")
    return files


def git_output(git_root: Path, *arguments: str) -> bytes:
    try:
        result = subprocess.run(
            ["git", "-C", str(git_root), *arguments],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except FileNotFoundError as error:
        raise ArchiveError("git is required to verify the archive") from error
    except subprocess.CalledProcessError as error:
        detail = error.stderr.decode("utf-8", errors="replace").strip()
        raise ArchiveError(f"git {' '.join(arguments)} failed: {detail}") from error
    return result.stdout


def load_inventory(repo_root: Path) -> list[dict[str, Any]]:
    inventory_path, _ = regular_file(
        repo_root, INVENTORY_PATH, "workflow archive inventory"
    )
    try:
        inventory = json.loads(inventory_path.read_bytes().decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ArchiveError(
            f"workflow archive inventory is invalid JSON: {error}"
        ) from error

    require(isinstance(inventory, dict), "workflow archive inventory must be an object")
    require(
        set(inventory)
        == {
            "schema",
            "baseline",
            "activeWorkflow",
            "archiveRoot",
            "files",
        },
        "workflow archive inventory has unexpected top-level fields",
    )
    require(inventory["schema"] == INVENTORY_SCHEMA, "workflow archive schema changed")
    require(
        inventory["baseline"]
        == {
            "repository": BASELINE_REPOSITORY,
            "commit": BASELINE_COMMIT,
            "workflowTree": BASELINE_WORKFLOW_TREE,
            "supportPaths": list(SUPPORT_PATHS),
        },
        "workflow archive baseline changed",
    )
    require(
        inventory["activeWorkflow"] == ACTIVE_WORKFLOW,
        "active workflow identity changed",
    )
    require(inventory["archiveRoot"] == ARCHIVE_ROOT, "archive root changed")

    files = inventory["files"]
    require(isinstance(files, list) and bool(files), "archive file inventory is empty")
    source_paths: list[str] = []
    archive_paths: list[str] = []
    for index, entry in enumerate(files):
        label = f"archive inventory entry {index}"
        require(isinstance(entry, dict), f"{label} must be an object")
        require(set(entry) == FILE_KEYS, f"{label} has unexpected fields")

        source = repository_relative_path(entry["sourcePath"], f"{label} sourcePath")
        require(
            source.startswith(f"{WORKFLOW_ROOT}/") or source in SUPPORT_PATHS,
            f"{label} sourcePath is outside the reviewed upstream automation set",
        )
        expected_archive = f"{ARCHIVE_ROOT}/{source}"
        archive = repository_relative_path(entry["archivePath"], f"{label} archivePath")
        require(archive == expected_archive, f"{label} archivePath is renamed")
        require(
            isinstance(entry["sourceMode"], str)
            and re.fullmatch(r"[0-7]{6}", entry["sourceMode"]) is not None,
            f"{label} sourceMode is invalid",
        )
        require(
            isinstance(entry["gitBlob"], str)
            and OBJECT_ID.fullmatch(entry["gitBlob"]) is not None,
            f"{label} gitBlob is invalid",
        )
        require(
            type(entry["bytes"]) is int and entry["bytes"] >= 0,
            f"{label} bytes is invalid",
        )
        require(
            isinstance(entry["sha256"], str)
            and SHA256.fullmatch(entry["sha256"]) is not None,
            f"{label} sha256 is invalid",
        )
        source_paths.append(source)
        archive_paths.append(archive)

    require(source_paths == sorted(source_paths), "archive inventory is not sorted")
    require(
        len(source_paths) == len(set(source_paths)), "archive sourcePath is duplicated"
    )
    require(
        len(archive_paths) == len(set(archive_paths)),
        "archive archivePath is duplicated",
    )
    return files


def baseline_files(git_root: Path) -> dict[str, tuple[str, str]]:
    resolved_commit = (
        git_output(git_root, "rev-parse", "--verify", f"{BASELINE_COMMIT}^{{commit}}")
        .decode("ascii")
        .strip()
    )
    require(
        resolved_commit == BASELINE_COMMIT, "baseline commit did not resolve exactly"
    )
    resolved_tree = (
        git_output(git_root, "rev-parse", f"{BASELINE_COMMIT}:{WORKFLOW_ROOT}")
        .decode("ascii")
        .strip()
    )
    require(resolved_tree == BASELINE_WORKFLOW_TREE, "baseline workflow tree changed")

    raw = git_output(
        git_root,
        "ls-tree",
        "-r",
        "-z",
        "--full-tree",
        BASELINE_COMMIT,
        "--",
        WORKFLOW_ROOT,
        *SUPPORT_PATHS,
    )
    entries: dict[str, tuple[str, str]] = {}
    for record in raw.split(b"\0"):
        if not record:
            continue
        try:
            metadata, raw_path = record.split(b"\t", 1)
            mode, object_type, object_id = metadata.decode("ascii").split()
            source = raw_path.decode("utf-8")
        except (UnicodeDecodeError, ValueError) as error:
            raise ArchiveError(
                "baseline workflow tree contains an unsupported entry"
            ) from error
        require(object_type == "blob", f"baseline path is not a blob: {source}")
        require(source not in entries, f"baseline path is duplicated: {source}")
        entries[source] = (mode, object_id)
    require(bool(entries), "baseline workflow tree is empty")
    return entries


def verify_active_workflow(repo_root: Path) -> Path:
    active_files = directory_files(
        repo_root, WORKFLOW_ROOT, "active workflow directory"
    )
    require(
        active_files == {ACTIVE_WORKFLOW},
        "active workflow directory must contain exactly axiomlayer-integration.yml",
    )
    active_path, _ = regular_file(repo_root, ACTIVE_WORKFLOW, "active workflow")
    return active_path


def verify_support_paths_are_quarantined(repo_root: Path) -> None:
    for source in SUPPORT_PATHS:
        path = safe_path(repo_root, source, "inherited automation support path")
        try:
            path.lstat()
        except FileNotFoundError:
            continue
        raise ArchiveError(
            f"inherited automation support path must be quarantined: {source}"
        )


def verify_repository(
    repo_root: Path, *, baseline_repository: Path | None = None
) -> list[Path]:
    repo_root = repo_root.absolute()
    try:
        root_mode = repo_root.lstat().st_mode
    except FileNotFoundError as error:
        raise ArchiveError(f"repository root is missing: {repo_root}") from error
    require(
        stat.S_ISDIR(root_mode) and not stat.S_ISLNK(root_mode),
        f"repository root is not a regular directory: {repo_root}",
    )
    git_root = (baseline_repository or repo_root).absolute()

    verify_active_workflow(repo_root)
    verify_support_paths_are_quarantined(repo_root)
    inventory = load_inventory(repo_root)
    baseline = baseline_files(git_root)
    inventory_sources = {entry["sourcePath"] for entry in inventory}
    require(
        inventory_sources == set(baseline),
        "archive inventory does not exactly cover the baseline workflow tree",
    )

    expected_archives = {entry["archivePath"] for entry in inventory}
    actual_archives = directory_files(repo_root, ARCHIVE_ROOT, "workflow archive")
    require(
        actual_archives == expected_archives,
        "workflow archive has missing, extra, or renamed files",
    )

    verified: list[Path] = []
    for entry in inventory:
        source = entry["sourcePath"]
        mode, object_id = baseline[source]
        require(mode == entry["sourceMode"], f"baseline mode mismatch: {source}")
        require(object_id == entry["gitBlob"], f"baseline Git blob mismatch: {source}")

        blob = git_output(git_root, "cat-file", "blob", f"{BASELINE_COMMIT}:{source}")
        digest = hashlib.sha256(blob).hexdigest()
        require(len(blob) == entry["bytes"], f"baseline byte count mismatch: {source}")
        require(digest == entry["sha256"], f"baseline SHA-256 mismatch: {source}")

        archive_path, archive_metadata = regular_file(
            repo_root, entry["archivePath"], "archived workflow"
        )
        archive_bytes = archive_path.read_bytes()
        require(archive_bytes == blob, f"archived workflow bytes differ: {source}")
        archive_is_executable = bool(archive_metadata.st_mode & 0o111)
        source_is_executable = mode == "100755"
        require(
            archive_is_executable == source_is_executable,
            f"archived workflow executable mode differs: {source}",
        )
        verified.append(archive_path)
    return verified


def main() -> int:
    try:
        arguments = sys.argv[1:]
        require(
            len(arguments) == 2 and arguments[0] == "--repository",
            "usage: verify-workflow-archive.py --repository ROOT",
        )
        verified = verify_repository(Path(arguments[1]))
    except (ArchiveError, OSError) as error:
        print(
            f"AxiomLayer workflow archive verification failed: {error}", file=sys.stderr
        )
        return 1
    print(
        "AxiomLayer workflow archive: "
        f"{len(verified)} baseline files and 1 active workflow verified"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
