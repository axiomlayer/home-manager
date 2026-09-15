#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "$script_dir/../.." && pwd)"
policy="$script_dir/policy.json"
lock="$script_dir/flake.lock"
archive_inventory="$script_dir/workflow-archive/inventory.json"
static_only=false

case "${1:-}" in
  "") ;;
  --static) static_only=true ;;
  *) printf 'usage: %s [--static]\n' "$0" >&2; exit 2 ;;
esac

fail() {
  printf 'axiomlayer Home Manager policy: %s\n' "$*" >&2
  exit 1
}

command -v jq >/dev/null 2>&1 || fail "jq is required"
[[ -f "$lock" ]] || fail "integration flake.lock is missing"

python3 "$script_dir/verify-workflow-archive.py" --repository "$repo_root"

"$script_dir/verify-nix-ci-bootstrap.sh" \
  "$script_dir/install-nix-ci.sh" \
  "$script_dir/nix-bootstrap.json" \
  "$repo_root/.github/workflows/axiomlayer-integration.yml"

expected_home_manager="$(jq -er '.source.commit' "$policy")"
expected_upstream_repository="$(jq -er '.source.upstream' "$policy")"
expected_nixpkgs="$(jq -er '.nixpkgs.commit' "$policy")"
expected_systems="$(jq -cS '.systems' "$policy")"

[[ "$(jq -er '.baseline.commit' "$archive_inventory")" == "$expected_home_manager" ]] \
  || fail "workflow archive baseline does not match the Home Manager policy commit"
[[ "$(jq -er '.baseline.repository' "$archive_inventory")" == "$expected_upstream_repository" ]] \
  || fail "workflow archive repository does not match the upstream policy identity"

[[ "$(jq -er '.source.repository' "$policy")" == "axiomlayer/home-manager" ]] \
  || fail "fork repository identity is not canonical"
[[ "$(jq -er '.source.defaultBranch' "$policy")" == "master" ]] \
  || fail "fork default branch is not canonical"

actual_home_manager="$(jq -er '.nodes["home-manager"].locked.rev' "$lock")"
actual_nixpkgs="$(jq -er '.nodes.nixpkgs.locked.rev' "$lock")"
[[ "$actual_home_manager" == "$expected_home_manager" ]] || fail "Home Manager lock drifted to $actual_home_manager"
[[ "$actual_nixpkgs" == "$expected_nixpkgs" ]] || fail "nixpkgs lock drifted to $actual_nixpkgs"

jq -e '
  .nodes["home-manager"].locked.owner == "axiomlayer"
  and .nodes["home-manager"].locked.repo == "home-manager"
  and .nodes["home-manager"].original.owner == "axiomlayer"
  and .nodes["home-manager"].original.repo == "home-manager"
  and .nodes.nixpkgs.locked.owner == "NixOS"
  and .nodes.nixpkgs.locked.repo == "nixpkgs"
  and (.nodes | to_entries | all(.value.locked? == null or (.value.locked.rev? | type == "string")))
' "$lock" >/dev/null || fail "lock file contains an unexpected or mutable input"

if [[ "$static_only" == false ]]; then
  command -v nix >/dev/null 2>&1 || fail "nix is required (use --static for the non-Nix policy checks)"
  actual_systems="$(nix eval --json "$script_dir#lib.fleetSystems" | jq -cS .)"
  [[ "$actual_systems" == "$expected_systems" ]] || fail "flake system set does not match policy"
fi

while IFS=: read -r workflow line_number action_line; do
  action="${action_line#*uses:}"
  action="${action%%#*}"
  action="${action//[[:space:]]/}"
  case "$action" in
    ./* | docker://*) continue ;;
  esac
  [[ "$action" =~ ^[^@]+@[0-9a-f]{40}$ ]] || fail "$workflow:$line_number uses a mutable action reference: $action"
done < <(grep -R -n -E '^[[:space:]]*(- )?uses:[[:space:]]+' "$repo_root/.github/workflows" || true)

python3 "$script_dir/verify-workflow-guards.py" --repository "$repo_root"

if git -C "$repo_root" cat-file -e "$expected_home_manager^{commit}" 2>/dev/null; then
  git -C "$repo_root" merge-base --is-ancestor "$expected_home_manager" HEAD \
    || fail "HEAD does not descend from the authoritative Home Manager commit"
fi

printf 'axiomlayer Home Manager policy: ok\n'
