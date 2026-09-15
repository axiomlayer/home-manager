# AxiomLayer fleet integration

This directory is the deliberately small compatibility gate between the
AxiomLayer fleet and the upstream Home Manager source tree. It does not copy
Home Manager's full upstream test matrix.

The lock anchors `axiomlayer/home-manager` at the `release-26.05` source commit
selected by the fleet promotion policy and evaluates that source with the
fleet's pinned `nixos-26.05` nixpkgs commit. CI overrides the Home Manager input
with the checked-out fork default-branch source without allowing the lock file
to change. A native runner then builds and activates a minimal configuration
for each supported Home Manager platform:

- `x86_64-linux`: Caracal, Cheetah, and Siberian WSL
- `aarch64-linux`: Sandcat and Ocelot WSL
- `aarch64-darwin`: Margay

The fixture installs only `hello`, enables the fleet's Bash/Zsh surfaces, and
writes a non-secret receipt under `.config/axiomlayer`. It uses no cache,
publisher, signing, cloud, enrollment, passphrase, or encryption credential.
The activation happens only in `/tmp/axiomlayer-home-manager` on an ephemeral
GitHub-hosted runner. The only executable workflow is
`.github/workflows/axiomlayer-integration.yml`; inherited upstream automation
cannot run in the AxiomLayer fork.

The complete `.github/workflows` tree inherited from
`nix-community/home-manager` commit
`ec172013fa62135f58fb58dd17ae9651e8f39727` is quarantined under
`integration/axiomlayer/workflow-archive/files`. The archive contains all
eight workflows plus the inherited Dependabot automation and labeler support
policy (the workflow directory had no other support files):

- `.github/dependabot.yml`
- `.github/labeler.yml`
- `.github/workflows/backport.yml`
- `.github/workflows/conflicts.yml`
- `.github/workflows/github_pages.yml`
- `.github/workflows/labeler.yml`
- `.github/workflows/tag-maintainers.yml`
- `.github/workflows/test.yml`
- `.github/workflows/update-maintainers.yml`
- `.github/workflows/validate-maintainers.yml`

`workflow-archive/inventory.json` records the full baseline commit and tree,
each source and archive path, Git mode and blob ID, byte count, and SHA-256.
`verify-workflow-archive.py` enumerates the baseline tree directly from Git and
adds the two explicit support paths, then requires exact inventory coverage. It
compares every regular, non-symlink archive file byte-for-byte with its matching
baseline blob. Missing, extra, renamed, linked, mode-drifted, or tampered
archive paths fail, as does any file besides the AxiomLayer integration
workflow under `.github/workflows` or restoration of either live support path.

The fork workflow runs proactively every day at 05:17 UTC and can also be
started manually without inputs. Every job independently requires the exact
`axiomlayer/home-manager` repository, the protected `refs/heads/master` ref,
the workflow identity
`axiomlayer/home-manager/.github/workflows/axiomlayer-integration.yml@refs/heads/master`,
and either the scheduled or manual event; all other repositories, refs,
workflow identities, and events skip every job. Its runner inventory is
limited to the fixed GitHub-hosted
`ubuntu-24.04`, `ubuntu-24.04-arm`, and `macos-15` labels. The workflow has only
read access to repository contents, uses no secret or credential context,
requires clean checkouts, never persists checkout authentication, and has no
synchronization, publication, release, or deployment path.

The workflow firewall recursively inventories `.github/workflows` and refuses
every extra workflow, support file, or symlink. It parses both AxiomLayer jobs
independently and requires the exact lowercase repository, protected master
ref, workflow identity, and event guard. Missing, duplicate, reordered,
weakened, inline, and top-level-OR guards are rejected. Every checkout must be
clean, must disable persisted credentials, and must use the same full action
commit. No other action, container image, service, runner group, self-hosted
label, write permission, secret, deployment environment, synchronization,
publication, direct network command, or external mutation surface is allowed.
Delegated Cachix or Determinate Nix installers are refused.

Hosted CI installs Nix through the fleet-standard wrapper. The dedicated
`nix-bootstrap.json` manifest binds the official launcher, the wrapper, and all
four native tarball digests; the wrapper then executes the launcher with the
credential environment removed. Adversarial policy checks refuse digest
drift, populated installer environments, credential references, persisted
checkout credentials, and delegated bootstrap actions before Nix executes.
The same tests reject trigger expansion, weekly-only cadence, manual inputs,
guard weakening, non-default or unprotected refs, wrong workflow identities,
repository substitution, non-clean checkouts, dynamic or private runner
selection, runner groups, write permissions, credential surfaces, source
overrides, mutable or additional actions, synchronization, publication,
release, deployment, and fail-open steps.

## Local verification

From the repository root:

```console
integration/axiomlayer/verify-policy.sh --static
integration/axiomlayer/verify-workflow-archive.py --repository "$PWD"
integration/axiomlayer/test-policy.sh
integration/axiomlayer/verify-policy.sh # when Nix is available
nix eval --json integration/axiomlayer#lib.activationDrvPaths \
  --override-input home-manager "path:$PWD" --no-write-lock-file
nix build --no-link \
  integration/axiomlayer#packages."$(nix eval --raw --impure --expr builtins.currentSystem)".activationPackage \
  --override-input home-manager "path:$PWD" --no-write-lock-file
```

A local machine proves only its native build. The workflow supplies the other
native architectures; physical device convergence remains a device-repository
acceptance responsibility.
