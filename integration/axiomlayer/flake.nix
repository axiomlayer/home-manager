{
  description = "AxiomLayer fleet acceptance for Home Manager release-26.05";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/c3eea5b2156db11c7eeeada3dc737711255b253e";

    home-manager = {
      url = "github:axiomlayer/home-manager/ec172013fa62135f58fb58dd17ae9651e8f39727";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs =
    { nixpkgs, home-manager, ... }:
    let
      systems = [
        "x86_64-linux"
        "aarch64-linux"
        "aarch64-darwin"
      ];

      configurationFor =
        system:
        let
          pkgs = import nixpkgs {
            inherit system;
            config.allowUnfree = false;
          };
        in
        home-manager.lib.homeManagerConfiguration {
          inherit pkgs;
          modules = [
            {
              home = {
                username = "runner";
                homeDirectory = "/tmp/axiomlayer-home-manager";
                stateVersion = "26.05";
                packages = [ pkgs.hello ];
                file.".config/axiomlayer/hello".source = "${pkgs.hello}/bin/hello";
                file.".config/axiomlayer/home-manager-fleet.json".text = builtins.toJSON {
                  schema = "axiom-home-manager-fleet-probe-v1";
                  inherit system;
                  source = "axiomlayer/home-manager";
                  upstreamRevision = "ec172013fa62135f58fb58dd17ae9651e8f39727";
                  nixpkgsRevision = "c3eea5b2156db11c7eeeada3dc737711255b253e";
                };
              };

              programs = {
                bash.enable = pkgs.stdenv.hostPlatform.isLinux;
                home-manager.enable = true;
                zsh.enable = true;
              };
            }
          ];
        };

      configurations = nixpkgs.lib.genAttrs systems configurationFor;
      activationPackages = nixpkgs.lib.mapAttrs (
        _: configuration: configuration.activationPackage
      ) configurations;
    in
    {
      checks = nixpkgs.lib.mapAttrs (_: activationPackage: {
        inherit activationPackage;
      }) activationPackages;
      packages = nixpkgs.lib.mapAttrs (_: activationPackage: {
        inherit activationPackage;
        default = activationPackage;
      }) activationPackages;
      homeConfigurations = nixpkgs.lib.mapAttrs' (
        system: configuration: nixpkgs.lib.nameValuePair "fleet-${system}" configuration
      ) configurations;
      lib = {
        fleetSystems = systems;
        activationDrvPaths = nixpkgs.lib.mapAttrs (
          _: activationPackage: builtins.unsafeDiscardStringContext activationPackage.drvPath
        ) activationPackages;
      };
    };
}
