# SPDX-License-Identifier: MIT
{ pkgs, self }:
let
  project = pkgs.vcpkg-purifier.buildVcpkgProject { src = ../examples/minimal; };
in
{
  foreign-projections = import ./foreign.nix {
    inherit pkgs;
    build = pkgs.vcpkg-purifier.buildVcpkgProject;
  };
  cli = self.packages.${pkgs.stdenv.hostPlatform.system}.default;
  environment = project.packages.environment;
  project = project.tests;
  release = project.release;
}
