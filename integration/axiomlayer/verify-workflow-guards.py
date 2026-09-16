#!/usr/bin/env python3
"""Enforce the executable workflow and inherited-job firewall."""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

OWNER_GUARD = "github.repository == 'nix-community/home-manager'"
FORK_WORKFLOW = "axiomlayer-integration.yml"
FORK_REPOSITORY = "axiomlayer/home-manager"
FORK_DEFAULT_REF = "refs/heads/master"
FORK_CRON = "17 5 * * *"
FORK_EXACT_WORKFLOW_REF = (
    f"{FORK_REPOSITORY}/.github/workflows/{FORK_WORKFLOW}@{FORK_DEFAULT_REF}"
)
FORK_SOURCE_EVIDENCE = f'.source == "{FORK_REPOSITORY}"'
FORK_JOB_GUARD = (
    f"github.repository == '{FORK_REPOSITORY}' "
    f"&& github.ref == '{FORK_DEFAULT_REF}' "
    "&& github.ref_protected == true "
    f"&& github.workflow_ref == '{FORK_EXACT_WORKFLOW_REF}' "
    "&& (github.event_name == 'schedule' "
    "|| github.event_name == 'workflow_dispatch')"
)
FORK_JOB_RUNNERS = {
    "policy": "ubuntu-24.04",
    "activation": "${{ matrix.runner }}",
}
FORK_MATRIX_RUNNERS = (
    "ubuntu-24.04",
    "ubuntu-24.04-arm",
    "macos-15",
)
JOB_KEY = re.compile(r"^  ([A-Za-z0-9_-]+):\s*$")
IF_KEY = re.compile(r"^    if:\s*(.*?)\s*$")
RUNS_ON_KEY = re.compile(r"^    runs-on:\s*(.*?)\s*$")
MATRIX_RUNNER_KEY = re.compile(r"^\s+runner:\s*([^#\s]+)(?:\s+#.*)?$")
USES_KEY = re.compile(r"^\s*(?:-\s+)?uses:\s*(['\"]?)([^'\"#\s]+)\1(?:\s+#.*)?$")
ACTION_REFERENCE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+@[0-9a-f]{40}$")
LIST_ITEM = re.compile(r"^(?P<indent>\s*)-\s+")
PERSIST_CREDENTIALS = re.compile(
    r"^\s*persist-credentials:\s*(?P<value>[^#\s]+)(?:\s+#.*)?$"
)
CLEAN_CHECKOUT = re.compile(r"^\s*clean:\s*(?P<value>[^#\s]+)(?:\s+#.*)?$")
LOCAL_NIX_WRAPPER = "integration/axiomlayer/install-nix-ci.sh"
CREDENTIAL_SURFACE = re.compile(
    r"GITHUB_TOKEN|GH_TOKEN|ACTIONS_RUNTIME_TOKEN|github\.token|"
    r"github_access_token|secrets(?:\.|\[)",
    re.IGNORECASE,
)
FORK_CREDENTIAL_SURFACE = re.compile(
    r"github\.token|secrets(?:\.|\[)|"
    r"\b(?:GITHUB_TOKEN|GH_TOKEN|ACTIONS_RUNTIME_TOKEN|ACTIONS_ID_TOKEN_REQUEST_TOKEN|"
    r"github_access_token)\b|"
    r"^\s*(?:token|password|passwd|credentials?|client-secret|private-key|ssh-key):",
    re.IGNORECASE,
)
FORK_CHECKOUT_OVERRIDE = re.compile(
    r"^\s*(?:repository|ref|token|ssh-key|ssh-known-hosts|github-server-url):",
    re.IGNORECASE,
)
FORK_SIDE_EFFECT_SURFACES = (
    (
        re.compile(
            r"\bgit\s+(?:push|pull|fetch|remote|tag|clone|send-pack)\b",
            re.IGNORECASE,
        ),
        "Git synchronization",
    ),
    (
        re.compile(r"\bnix-community/home-manager\b", re.IGNORECASE),
        "upstream source selection",
    ),
    (re.compile(r"\b(?:gh|hub)\s+", re.IGNORECASE), "GitHub mutation tooling"),
    (
        re.compile(r"\b(?:curl|wget|scp|rsync|ssh)\b", re.IGNORECASE),
        "direct external network tooling",
    ),
    (
        re.compile(
            r"\b(?:npm|pnpm|yarn|cargo|twine|gem|docker|nix)\s+"
            r"(?:publish|push|copy)\b",
            re.IGNORECASE,
        ),
        "publishing",
    ),
    (
        re.compile(r"\b(?:release|publish|deploy(?:ment)?)\b", re.IGNORECASE),
        "release or deployment",
    ),
    (
        re.compile(r"^\s*environment\s*:", re.IGNORECASE),
        "deployment environment",
    ),
    (
        re.compile(r"^\s*(?:container|services|image)\s*:", re.IGNORECASE),
        "container image or service",
    ),
    (
        re.compile(r"\b(?:repository_dispatch|workflow_run)\b", re.IGNORECASE),
        "workflow chaining",
    ),
    (
        re.compile(r"^\s*continue-on-error\s*:\s*true\s*$", re.IGNORECASE),
        "fail-open execution",
    ),
)
FORBIDDEN_BOOTSTRAP_MARKERS = (
    "cachix/",
    "determinatesystems/nix-installer",
    "install.determinate.systems",
)


class GuardError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise GuardError(message)


def top_level_or(expression: str) -> bool:
    depth = 0
    quote: str | None = None
    index = 0
    while index < len(expression):
        character = expression[index]
        if quote is not None:
            if character == quote:
                quote = None
            index += 1
            continue
        if character in ("'", '"'):
            quote = character
        elif character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
            require(depth >= 0, "owner guard has an unmatched closing parenthesis")
        elif expression[index : index + 2] == "||" and depth == 0:
            return True
        index += 1
    require(quote is None, "owner guard has an unterminated quote")
    require(depth == 0, "owner guard has unbalanced parentheses")
    return False


def job_blocks(text: str, label: str) -> dict[str, list[str]]:
    lines = text.splitlines()
    jobs_lines = [index for index, line in enumerate(lines) if line == "jobs:"]
    require(len(jobs_lines) == 1, f"{label}: expected one jobs mapping")
    start = jobs_lines[0] + 1
    blocks: dict[str, list[str]] = {}
    current: str | None = None
    for line in lines[start:]:
        if line and not line.startswith(" ") and not line.lstrip().startswith("#"):
            break
        match = JOB_KEY.fullmatch(line)
        if match:
            current = match.group(1)
            require(current not in blocks, f"{label}: duplicate job {current}")
            blocks[current] = [line]
            continue
        if (
            line.startswith("  ")
            and not line.startswith("    ")
            and line.strip()
            and not line.lstrip().startswith("#")
        ):
            raise GuardError(
                f"{label}: unsupported inline or malformed job: {line.strip()}"
            )
        if current is not None:
            blocks[current].append(line)
    require(bool(blocks), f"{label}: jobs mapping is empty")
    return blocks


def job_condition(block: list[str], label: str) -> str:
    matches: list[tuple[int, str]] = []
    for index, line in enumerate(block):
        match = IF_KEY.fullmatch(line)
        if match:
            matches.append((index, match.group(1)))
    require(len(matches) == 1, f"{label}: expected exactly one job-level if")
    index, value = matches[0]
    if value in (">", ">-", "|", "|-"):
        continuation: list[str] = []
        for line in block[index + 1 :]:
            if line.strip() and len(line) - len(line.lstrip()) <= 4:
                break
            if line.strip() and not line.lstrip().startswith("#"):
                continuation.append(line.strip())
        value = " ".join(continuation)
    require(bool(value), f"{label}: job-level if is empty")
    return " ".join(value.replace("${{", "").replace("}}", "").split())


def active_lines(lines: list[str]) -> list[str]:
    return [
        line for line in lines if line.strip() and not line.lstrip().startswith("#")
    ]


def top_level_block(text: str, key: str, label: str) -> list[str]:
    lines = text.splitlines()
    header = f"{key}:"
    starts = [index for index, line in enumerate(lines) if line == header]
    require(len(starts) == 1, f"{label}: expected one top-level {key} mapping")
    start = starts[0] + 1
    end = len(lines)
    for index in range(start, len(lines)):
        line = lines[index]
        if line.strip() and not line.startswith(" ") and not line.startswith("#"):
            end = index
            break
    return lines[start:end]


def verify_fork_triggers(text: str, label: str) -> None:
    trigger_lines = active_lines(top_level_block(text, "on", label))
    require(
        len(trigger_lines) == 3,
        f"{label}: only one schedule and an input-free manual trigger are allowed",
    )
    require(trigger_lines[0] == "  schedule:", f"{label}: schedule trigger is missing")
    cron = re.fullmatch(r"    - cron:\s*(['\"])([^'\"]+)\1", trigger_lines[1])
    require(cron is not None, f"{label}: expected one quoted cron schedule")
    cron_fields = cron.group(2).split()
    require(
        len(cron_fields) == 5
        and cron_fields[0].isdigit()
        and 1 <= int(cron_fields[0]) <= 59
        and cron_fields[2:] == ["*", "*", "*"]
        and cron.group(2) == FORK_CRON,
        f"{label}: schedule must use the reviewed daily cadence",
    )
    require(
        trigger_lines[2] == "  workflow_dispatch:",
        f"{label}: manual trigger must not accept inputs",
    )


def verify_fork_permissions(text: str, label: str) -> None:
    declarations = [
        line
        for line in active_lines(text.splitlines())
        if re.match(r"^\s*permissions\s*:", line)
    ]
    require(
        declarations == ["permissions:"],
        f"{label}: permissions must be declared once at workflow scope",
    )
    require(
        active_lines(top_level_block(text, "permissions", label))
        == ["  contents: read"],
        f"{label}: the workflow token must be contents-read-only",
    )


def verify_fork_jobs(text: str, label: str) -> None:
    blocks = job_blocks(text, label)
    require(
        tuple(blocks) == tuple(FORK_JOB_RUNNERS),
        f"{label}: fork job inventory changed",
    )
    for job, expected_runner in FORK_JOB_RUNNERS.items():
        block = blocks[job]
        require(
            job_condition(block, f"{label}:{job}") == FORK_JOB_GUARD,
            f"{label}:{job}: repository, ref, and event guard must match exactly",
        )
        runner_values = [
            match.group(1) for line in block if (match := RUNS_ON_KEY.fullmatch(line))
        ]
        require(
            runner_values == [expected_runner],
            f"{label}:{job}: runner selection is not the reviewed hosted label",
        )

    matrix_runners = [
        match.group(1)
        for line in text.splitlines()
        if (match := MATRIX_RUNNER_KEY.fullmatch(line))
    ]
    require(
        tuple(matrix_runners) == FORK_MATRIX_RUNNERS,
        f"{label}: matrix runner inventory is not the reviewed hosted set",
    )


def verify_fork_actions(text: str, label: str) -> None:
    lines = text.splitlines()
    actions: list[str] = []
    for index, line in enumerate(lines):
        stripped = line.lstrip()
        if stripped.startswith("#") or not re.match(r"^(?:-\s+)?uses\s*:", stripped):
            continue
        match = USES_KEY.fullmatch(line)
        require(match is not None, f"{label}:{index + 1}: malformed action reference")
        action = match.group(2)
        require(
            ACTION_REFERENCE.fullmatch(action) is not None,
            f"{label}:{index + 1}: action is not pinned to a full commit SHA",
        )
        actions.append(action)
        if action.startswith("actions/checkout@"):
            require_nonpersisting_checkout(lines, index, label)
            require_clean_checkout(lines, index, label)
            block = step_block(lines, index, label)
            for step_line in active_lines(block):
                require(
                    FORK_CHECKOUT_OVERRIDE.search(step_line) is None,
                    f"{label}:{index + 1}: checkout may not override source or authentication",
                )

    require(len(actions) == 2, f"{label}: action inventory changed")
    require(
        all(action.startswith("actions/checkout@") for action in actions),
        f"{label}: only the pinned checkout action is allowed",
    )
    require(
        len(set(actions)) == 1,
        f"{label}: checkout jobs must use the same reviewed commit",
    )


def verify_fork_surfaces(text: str, label: str) -> None:
    require(
        text.count(FORK_SOURCE_EVIDENCE) == 1,
        f"{label}: activation evidence must use the canonical fork identity",
    )
    for index, line in enumerate(text.splitlines()):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        require(
            FORK_CREDENTIAL_SURFACE.search(line) is None,
            f"{label}:{index + 1}: credential or secret surface is forbidden",
        )
        for pattern, surface in FORK_SIDE_EFFECT_SURFACES:
            require(
                pattern.search(line) is None,
                f"{label}:{index + 1}: {surface} is forbidden",
            )


def verify_fork_workflow(text: str, label: str = "fork workflow") -> None:
    verify_workflow_safety(text, label)
    verify_fork_triggers(text, label)
    verify_fork_permissions(text, label)
    verify_fork_jobs(text, label)
    verify_fork_actions(text, label)
    verify_fork_surfaces(text, label)


def verify_owner_guards(text: str, label: str = "workflow") -> None:
    for job, block in job_blocks(text, label).items():
        expression = job_condition(block, f"{label}:{job}")
        require(
            not top_level_or(expression),
            f"{label}:{job}: top-level OR can bypass the owner guard",
        )
        require(
            expression == OWNER_GUARD or expression.startswith(OWNER_GUARD + " &&"),
            f"{label}:{job}: owner guard is not the mandatory first conjunct",
        )


def step_block(lines: list[str], index: int, label: str) -> list[str]:
    uses_indent = len(lines[index]) - len(lines[index].lstrip())
    start: int | None = None
    step_indent = -1
    for candidate in range(index, -1, -1):
        match = LIST_ITEM.match(lines[candidate])
        if match and len(match.group("indent")) <= uses_indent:
            start = candidate
            step_indent = len(match.group("indent"))
            break
    require(start is not None, f"{label}:{index + 1}: action is not inside a step")

    end = len(lines)
    for candidate in range(start + 1, len(lines)):
        line = lines[candidate]
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip())
        list_match = LIST_ITEM.match(line)
        if (list_match and indent <= step_indent) or indent < step_indent:
            end = candidate
            break
    return lines[start:end]


def require_nonpersisting_checkout(lines: list[str], index: int, label: str) -> None:
    block = step_block(lines, index, label)
    values = [
        match.group("value")
        for line in block
        if (match := PERSIST_CREDENTIALS.match(line))
    ]
    require(
        values == ["false"],
        f"{label}:{index + 1}: checkout must set persist-credentials: false exactly once",
    )


def require_clean_checkout(lines: list[str], index: int, label: str) -> None:
    block = step_block(lines, index, label)
    values = [
        match.group("value") for line in block if (match := CLEAN_CHECKOUT.match(line))
    ]
    require(
        values == ["true"],
        f"{label}:{index + 1}: checkout must set clean: true exactly once",
    )


def verify_workflow_safety(text: str, label: str = "workflow") -> None:
    lines = text.splitlines()
    for index, line in enumerate(lines):
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue
        lowered = line.lower()
        for marker in FORBIDDEN_BOOTSTRAP_MARKERS:
            require(
                marker not in lowered,
                f"{label}:{index + 1}: delegated Nix bootstrap is forbidden",
            )

        action_match = USES_KEY.match(line)
        if action_match and action_match.group(2).lower().startswith(
            "actions/checkout@"
        ):
            require_nonpersisting_checkout(lines, index, label)

        if LOCAL_NIX_WRAPPER in line:
            block = step_block(lines, index, label)
            for step_line in block:
                if step_line.lstrip().startswith("#"):
                    continue
                require(
                    CREDENTIAL_SURFACE.search(step_line) is None,
                    f"{label}:{index + 1}: credential is routed to the Nix wrapper step",
                )


def executable_workflows(repo_root: Path) -> list[Path]:
    workflow_root = repo_root / ".github" / "workflows"
    require(workflow_root.is_dir(), f"{workflow_root}: workflow directory is missing")
    require(not workflow_root.is_symlink(), f"{workflow_root}: unsafe workflow path")
    paths: list[Path] = []
    for directory, directory_names, file_names in os.walk(
        workflow_root, followlinks=False
    ):
        directory_path = Path(directory)
        for name in directory_names:
            path = directory_path / name
            require(not path.is_symlink(), f"{path}: unsafe workflow path")
        for name in file_names:
            path = directory_path / name
            require(
                path.is_file() and not path.is_symlink(),
                f"{path}: unsafe workflow path",
            )
            paths.append(path)
    paths.sort()
    expected = workflow_root / FORK_WORKFLOW
    require(
        paths == [expected],
        f"{workflow_root}: expected exactly one executable workflow: {FORK_WORKFLOW}",
    )
    return paths


def verify_repository(repo_root: Path) -> list[Path]:
    paths = executable_workflows(repo_root)
    for path in paths:
        text = path.read_text(encoding="utf-8")
        verify_fork_workflow(text, str(path))
    return paths


def verify_text(text: str, label: str = "workflow") -> None:
    verify_workflow_safety(text, label)
    verify_owner_guards(text, label)


def main() -> int:
    try:
        arguments = sys.argv[1:]
        require(
            bool(arguments),
            "usage: verify-workflow-guards.py [--repository ROOT | WORKFLOW...]",
        )
        if arguments[0] == "--repository":
            require(len(arguments) == 2, "--repository requires exactly one root")
            paths = verify_repository(Path(arguments[1]))
            print(f"Home Manager workflow firewall: {len(paths)} files verified")
            return 0
        for argument in arguments:
            path = Path(argument)
            text = path.read_text(encoding="utf-8")
            if path.name == FORK_WORKFLOW:
                verify_fork_workflow(text, str(path))
            else:
                verify_text(text, str(path))
    except (GuardError, OSError) as error:
        print(
            f"Home Manager workflow guard verification failed: {error}", file=sys.stderr
        )
        return 1
    print(f"Home Manager workflow guards: {len(arguments)} files verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
