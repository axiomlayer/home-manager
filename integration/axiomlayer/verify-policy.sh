#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "$script_dir/../.." && pwd)"
policy="$script_dir/policy.json"
lock="$script_dir/flake.lock"
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

expected_home_manager="$(jq -er '.source.commit' "$policy")"
expected_nixpkgs="$(jq -er '.nixpkgs.commit' "$policy")"
expected_systems="$(jq -cS '.systems' "$policy")"

actual_home_manager="$(jq -er '.nodes["home-manager"].locked.rev' "$lock")"
actual_nixpkgs="$(jq -er '.nodes.nixpkgs.locked.rev' "$lock")"
[[ "$actual_home_manager" == "$expected_home_manager" ]] || fail "Home Manager lock drifted to $actual_home_manager"
[[ "$actual_nixpkgs" == "$expected_nixpkgs" ]] || fail "nixpkgs lock drifted to $actual_nixpkgs"

jq -e '
  .nodes["home-manager"].locked.owner == "AxiomLayer"
  and .nodes["home-manager"].locked.repo == "home-manager"
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

for workflow in backport.yml conflicts.yml github_pages.yml labeler.yml tag-maintainers.yml test.yml update-maintainers.yml validate-maintainers.yml; do
  grep -Fq "github.repository == 'nix-community/home-manager'" "$repo_root/.github/workflows/$workflow" \
    || fail "$workflow is not strictly inert outside the upstream repository"
done

if git -C "$repo_root" cat-file -e "$expected_home_manager^{commit}" 2>/dev/null; then
  git -C "$repo_root" merge-base --is-ancestor "$expected_home_manager" HEAD \
    || fail "HEAD does not descend from the authoritative Home Manager commit"
fi

printf 'axiomlayer Home Manager policy: ok\n'
