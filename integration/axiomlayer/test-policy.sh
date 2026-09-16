#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "$script_dir/../.." && pwd)"
wrapper="$script_dir/install-nix-ci.sh"
manifest="$script_dir/nix-bootstrap.json"
workflow="$repo_root/.github/workflows/axiomlayer-integration.yml"
verifier="$script_dir/verify-nix-ci-bootstrap.sh"

"$script_dir/verify-policy.sh" --static
python3 "$script_dir/test_workflow_guards.py"
python3 "$script_dir/test_workflow_archive.py"

test_root="$(mktemp -d "${TMPDIR:-/tmp}/home-manager-nix-bootstrap.XXXXXXXX")"
trap 'rm -rf "$test_root"' EXIT HUP INT TERM

cp "$wrapper" "$test_root/wrapper"
cp "$manifest" "$test_root/nix-bootstrap.json"
cp "$workflow" "$test_root/workflow.yml"

printf '%s\n' '# digest drift' >> "$test_root/wrapper"
if "$verifier" "$test_root/wrapper" "$test_root/nix-bootstrap.json" "$test_root/workflow.yml" >/dev/null 2>&1; then
  echo "bootstrap verifier accepted wrapper digest drift" >&2
  exit 1
fi

sed 's/env -i/env/' "$wrapper" > "$test_root/wrapper"
if "$verifier" "$test_root/wrapper" "$test_root/nix-bootstrap.json" "$test_root/workflow.yml" >/dev/null 2>&1; then
  echo "bootstrap verifier accepted a populated environment" >&2
  exit 1
fi

cp "$wrapper" "$test_root/wrapper"
printf '%s\n' '# GITHUB_TOKEN' >> "$test_root/wrapper"
if "$verifier" "$test_root/wrapper" "$test_root/nix-bootstrap.json" "$test_root/workflow.yml" >/dev/null 2>&1; then
  echo "bootstrap verifier accepted a credential reference" >&2
  exit 1
fi

cp "$wrapper" "$test_root/wrapper"
printf '%s\n' '# cachix/install-nix-action@0000000000000000000000000000000000000000' \
  >> "$test_root/workflow.yml"
if "$verifier" "$test_root/wrapper" "$test_root/nix-bootstrap.json" "$test_root/workflow.yml" >/dev/null 2>&1; then
  echo "bootstrap verifier accepted delegated installation" >&2
  exit 1
fi

cp "$workflow" "$test_root/workflow.yml"
jq '.installerSha256 = ("0" * 64)' "$manifest" > "$test_root/nix-bootstrap.json"
if "$verifier" "$test_root/wrapper" "$test_root/nix-bootstrap.json" "$test_root/workflow.yml" >/dev/null 2>&1; then
  echo "bootstrap verifier accepted installer digest drift" >&2
  exit 1
fi

printf 'axiomlayer Home Manager adversarial policy checks: ok\n'
