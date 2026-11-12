# SPDX-License-Identifier: MIT
{
  lib,
  runCommand,
  fetchurl,
  writeText,
  python3,
  native,
  toolchain,
  purifier,
  stdenv,
  gnutar,
  gzip,
}:
{
  src,
  lockFile ? src + "/vcpkg-purifier.lock.json",
  vcpkgLock ? src + "/vcpkg-lock.json",
  fetchers ? { },
  nativeLibraries ? { },
  nativeIncludeDirectories ? [ ],
  resourceRoots ? { },
  resourceDependencies ? [ ],
  resourceSchema ? null,
  cmakeFlags ? [ ],
  buildTargets ? [ ],
  test ? true,
  nativeBuildInputs ? [ ],
  srcFilter ?
    path: type:
    !(builtins.elem (baseNameOf path) [
      ".git"
      ".vcpkg-purifier"
      "vcpkg_installed"
      "build"
      "result"
      "__pycache__"
    ]),
}:
let
  lock = purifier.checkLock (
    import ../../lib-overlays/default/read-lock.nix { inherit lib; } { inherit src lockFile vcpkgLock; }
  );
  environment = import ./environment.nix {
    inherit
      lib
      runCommand
      fetchurl
      writeText
      python3
      native
      toolchain
      purifier
      ;
  } { inherit lock fetchers; };
  profile = lock.data.profiles.${toolchain.system};
  source = lib.cleanSourceWith {
    inherit src;
    filter = srcFilter;
  };
  builtProject =
    runCommand "purified-vcpkg-project"
      {
        nativeBuildInputs = [
          toolchain
          python3
        ]
        ++ nativeBuildInputs;
      }
      ''
            export HOME="$TMPDIR/home"
            export XDG_CACHE_HOME="$TMPDIR/cache"
            export VCPKG_ROOT=${environment}/root
            export VCPKG_DISABLE_METRICS=1 VCPKG_FORCE_SYSTEM_BINARIES=1
            export VCPKG_BINARY_SOURCES=clear
        unset VCPKG_OVERLAY_PORTS VCPKG_OVERLAY_TRIPLETS VCPKG_FEATURE_FLAGS
            export X_VCPKG_ASSET_SOURCES="clear;x-azurl,file://${environment}/assets;x-block-origin"
            export NIX_VCPKG_WRITABLE_PATH="$TMPDIR/vcpkg"
            mkdir -p "$HOME" source "$out"
            cp -r ${source}/. source/
            chmod -R u+w source
            cp -r ${environment}/installed installed
            chmod -R u+w installed
            cmake -S source -B build \
              -DCMAKE_TOOLCHAIN_FILE=${environment}/root/scripts/buildsystems/vcpkg.cmake \
              -DVCPKG_MANIFEST_DIR=${environment}/manifest \
              -DVCPKG_INSTALLED_DIR="$PWD/installed" \
              -DVCPKG_TARGET_TRIPLET=${profile.triplet} -DVCPKG_HOST_TRIPLET=${profile.triplet} \
              -DVCPKG_MANIFEST_FEATURES=${lib.escapeShellArg (lib.concatStringsSep ";" profile.features)} \
              -DCMAKE_INSTALL_PREFIX="$out" ${lib.escapeShellArgs cmakeFlags}
            cmake --build build ${
              lib.optionalString (buildTargets != [ ]) ("--target " + lib.escapeShellArgs buildTargets)
            }
            ${lib.optionalString test "ctest --test-dir build --output-on-failure"}
            cmake --install build
      '';
  projections =
    lib.optionalAttrs (nativeLibraries != { }) (
      purifier.nativeProjections {
        producer = builtProject;
        libraries = nativeLibraries;
        includeDirectories = nativeIncludeDirectories;
        system = stdenv.hostPlatform.system;
        targetMetadata.tool = "vcpkg";
        inherit runCommand python3;
      }
    )
    // lib.optionalAttrs (resourceRoots != { }) (
      purifier.resourceProjections {
        producer = builtProject;
        roots = resourceRoots;
        dependencies = resourceDependencies;
        schema = resourceSchema;
        inherit runCommand python3;
      }
    );
  project = builtProject // {
    inherit projections;
  };
  release =
    assert lock.problems == [ ];
    runCommand "vcpkg-project-release"
      {
        nativeBuildInputs = [
          gnutar
          gzip
        ];
      }
      ''
        mkdir source "$out"
        cp -r ${source}/. source/
        chmod -R u+w source
        cp ${lockFile} source/vcpkg-purifier.lock.json
        cp ${vcpkgLock} source/vcpkg-lock.json
        tar --sort=name --mtime=@1 --owner=0 --group=0 --numeric-owner -C source -cf - . | gzip -n > "$out/project.tar.gz"
      '';
in
{
  packages = {
    inherit project environment;
    default = project;
  };
  tests = project;
  inherit release projections;
  fetches = lock.entries;
}
