# AxiomLayer fleet integration

This directory is the deliberately small compatibility gate between the
AxiomLayer fleet and the upstream Home Manager source tree. It does not copy
Home Manager's full upstream test matrix.

The lock anchors `AxiomLayer/home-manager` at the `release-26.05` source commit
selected by the fleet promotion policy and evaluates that source with the
fleet's pinned `nixos-26.05` nixpkgs commit. CI overrides the Home Manager input
with the checked-out pull-request source without allowing the lock file to
change. A native runner then builds and activates a minimal configuration for
each supported Home Manager platform:

- `x86_64-linux`: Caracal, Cheetah, and Siberian WSL
- `aarch64-linux`: Sandcat and Ocelot WSL
- `aarch64-darwin`: Margay

The fixture installs only `hello`, enables the fleet's Bash/Zsh surfaces, and
writes a non-secret receipt under `.config/axiomlayer`. It uses no cache,
publisher, signing, cloud, enrollment, passphrase, or encryption credential.
The activation happens only in `/tmp/axiomlayer-home-manager` on an ephemeral
GitHub-hosted runner. Every inherited upstream workflow is repository-guarded;
only this compatibility gate runs in the AxiomLayer fork.

## Local verification

From the repository root:

```console
integration/axiomlayer/verify-policy.sh --static
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
