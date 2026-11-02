# SPDX-License-Identifier: MIT
{
  project,
  lockFile,
  vcpkgLock,
  target,
}:
let
  pkgs = import (/. + "@nixpkgs@") { };
  purifier = import (/. + "@purifier@/nix/lib") { inherit (pkgs) lib; };
  native = pkgs.callPackage ./native.nix { };
  toolchain = pkgs.buildEnv {
    name = "vcpkg-purifier-toolchain";
    paths = [
      native
      pkgs.stdenv.cc
      pkgs.pkg-config
      pkgs.patchelf
      pkgs.cmake
      pkgs.ninja
      pkgs.gnumake
      pkgs.git
      pkgs.curl
      pkgs.python3
      pkgs.clang-tools
      pkgs.coreutils
      pkgs.findutils
      pkgs.gnused
      pkgs.gnugrep
      pkgs.bash
      pkgs.patch
    ];
  };
  args = {
    src = /. + project;
    lockFile = /. + lockFile;
    vcpkgLock = /. + vcpkgLock;
  };
  lock = import ./read-lock.nix { inherit (pkgs) lib; } args;
in
if target == "environment" then
  pkgs.callPackage ./environment.nix { inherit purifier native toolchain; } { inherit lock; }
else if target == "runtime" then
  pkgs.runCommand "vcpkg-purifier-runtime" { } ''ln -s @runtime@ "$out"''
else if target == "release" then
  (pkgs.callPackage ./build-project.nix { inherit purifier native toolchain; } args).release
else
  throw "vcpkg-purifier: unknown realization target ${target}"
