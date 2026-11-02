# SPDX-License-Identifier: MIT
{
  description = "Locked, Nix-resolved dependencies for vcpkg";
  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
  inputs.purifier = {
    url = "github:nix-purifiers/purifier";
    flake = false;
  };
  outputs =
    {
      self,
      nixpkgs,
      purifier,
    }:
    let
      systems = [
        "x86_64-linux"
        "aarch64-linux"
      ];
      forAll = nixpkgs.lib.genAttrs systems;
      shared = lib: import (purifier + "/nix/lib") { inherit lib; };
      overlay = final: prev: {
        vcpkg-purifier = final.lib.makeScope final.newScope (scope: {
          native = scope.callPackage ./nix/native.nix { };
          toolchain = final.buildEnv {
            name = "vcpkg-purifier-toolchain";
            paths = [
              scope.native
              final.stdenv.cc
              final.pkg-config
              final.patchelf
              final.cmake
              final.ninja
              final.gnumake
              final.git
              final.curl
              final.python3
              final.clang-tools
              final.coreutils
              final.findutils
              final.gnused
              final.gnugrep
              final.bash
              final.patch
            ];
          };
          cli = scope.callPackage ./nix/cli.nix {
            nixpkgsSrc = nixpkgs;
            purifierSrc = purifier;
          };
          buildVcpkgProject = scope.callPackage ./nix/build-project.nix { purifier = shared final.lib; };
        });
      };
      pkgsFor =
        system:
        import nixpkgs {
          inherit system;
          overlays = [ overlay ];
        };
    in
    {
      overlays.default = overlay;
      lib.vcpkg-purifier.readLock = import ./nix/read-lock.nix { lib = nixpkgs.lib; };
      packages = forAll (system: {
        default = (pkgsFor system).vcpkg-purifier.cli;
        cli = self.packages.${system}.default;
      });
      apps = forAll (system: {
        default = {
          type = "app";
          program = "${self.packages.${system}.default}/bin/vcpkg-purifier";
          meta.description = "Lock and prefetch vcpkg dependencies";
        };
      });
      formatter = forAll (system: (pkgsFor system).nixfmt-tree);
      checks = forAll (
        system:
        import ./tests {
          pkgs = pkgsFor system;
          inherit self;
        }
      );
    };
}
