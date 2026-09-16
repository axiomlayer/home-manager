#!/usr/bin/env bash
set -euo pipefail

if [[ "$#" -ne 3 ]]; then
  printf 'usage: %s <wrapper> <nix-bootstrap.json> <workflow.yml>\n' "$0" >&2
  exit 2
fi

wrapper="$1"
manifest="$2"
workflow="$3"

fail() {
  printf 'axiomlayer Home Manager Nix bootstrap: %s\n' "$*" >&2
  exit 1
}

hash_file() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  else
    shasum -a 256 "$1" | awk '{print $1}'
  fi
}

[[ -f "$wrapper" && ! -L "$wrapper" ]] || fail "wrapper is missing or linked"
[[ -f "$manifest" && ! -L "$manifest" ]] || fail "manifest is missing or linked"
[[ -f "$workflow" && ! -L "$workflow" ]] || fail "workflow is missing or linked"

jq -e '. == {
  schema: "axiomlayer-nix-bootstrap-v1",
  version: "2.35.2",
  installUrl: "https://releases.nixos.org/nix/nix-2.35.2/install",
  installerSha256: "9adda97297d9e8ab360df95c729eabff4f4f93d6db091953c3a68f29e3fb130c",
  wrapperSha256: "e687c31d4b2297bf6f217e1f95bd903b0dba189e81e024224c807836a200e411",
  binaryTarballSha256: {
    "aarch64-darwin": "1695c13aba5afa7c2ecd6dc4a9393f602e7bbc440ed45e81602c831546580ec3",
    "x86_64-darwin": "d725518d89f3b0b8d4af702a9d38d519814014cbe125afb3ed0545c9d755f6a5",
    "aarch64-linux": "4d0302a2910f5eec1c33b8deef634f04899a75737e7001ec49908d003ae5efda",
    "x86_64-linux": "0c3960a9792331a22081c3c7a5d8465db9b17c50b3acdf18587fa4c6f2cb1158"
  }
}' "$manifest" >/dev/null || fail "manifest diverges from reviewed fleet Nix pins"

while IFS= read -r boundary; do
  grep -F -- "$boundary" "$wrapper" >/dev/null || fail "wrapper lost boundary: $boundary"
done <<'EOF'
NIX_VERSION=2.35.2
INSTALLER_URL=https://releases.nixos.org/nix/nix-2.35.2/install
INSTALLER_SHA256=9adda97297d9e8ab360df95c729eabff4f4f93d6db091953c3a68f29e3fb130c
env -i
--no-channel-add --no-modify-profile
1695c13aba5afa7c2ecd6dc4a9393f602e7bbc440ed45e81602c831546580ec3
d725518d89f3b0b8d4af702a9d38d519814014cbe125afb3ed0545c9d755f6a5
4d0302a2910f5eec1c33b8deef634f04899a75737e7001ec49908d003ae5efda
0c3960a9792331a22081c3c7a5d8465db9b17c50b3acdf18587fa4c6f2cb1158
EOF

if grep -E 'GITHUB_TOKEN|GH_TOKEN|ACTIONS_RUNTIME_TOKEN|github\.token|github_access_token' \
  "$wrapper" >/dev/null; then
  fail "wrapper references a live credential surface"
fi

expected_wrapper="$(jq -er '.wrapperSha256' "$manifest")"
actual_wrapper="$(hash_file "$wrapper")"
[[ "$actual_wrapper" == "$expected_wrapper" ]] || fail "wrapper digest changed"

[[ "$(grep -c 'uses: actions/checkout@' "$workflow")" -eq 2 ]] ||
  fail "workflow checkout inventory changed"
[[ "$(grep -c 'persist-credentials: false' "$workflow")" -eq 2 ]] ||
  fail "a workflow checkout can persist credentials"
[[ "$(grep -c 'clean: true' "$workflow")" -eq 2 ]] ||
  fail "a workflow checkout can retain an unclean workspace"
[[ "$(grep -c 'run: integration/axiomlayer/install-nix-ci.sh' "$workflow")" -eq 2 ]] ||
  fail "workflow must use the reviewed wrapper twice"
if grep -E 'cachix/install-nix-action@|github\.token|github_access_token|secrets\.|permissions:.*write' \
  "$workflow" >/dev/null; then
  fail "workflow delegates bootstrap or exposes a credential"
fi

printf 'axiomlayer Home Manager Nix bootstrap: ok\n'
