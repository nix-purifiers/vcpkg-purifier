# SPDX-License-Identifier: MIT
{ vcpkg, vcpkg-tool }:
vcpkg.override {
  vcpkg-tool = vcpkg-tool.overrideAttrs (old: {
    # Nixpkgs moves the root lock out of the immutable registry, but hardcodes
    # /tmp. Honor the caller's temporary directory on restricted hosts too.
    postPatch = (old.postPatch or "") + ''
      substituteInPlace src/vcpkg/vcpkgpaths.cpp \
        --replace-fail 'Path{"/tmp/vcpkg"}' '(Path{get_environment_variable("TMPDIR").value_or("/tmp")} / "vcpkg")'
    '';
  });
}
