# SPDX-License-Identifier: MIT
{
  lib,
  stdenvNoCC,
  makeWrapper,
  python3,
  nix,
  gh,
  native,
  toolchain,
  cmake,
  clang-tools,
  cacert,
  nixpkgsSrc,
  purifierSrc,
}:
stdenvNoCC.mkDerivation {
  pname = "vcpkg-purifier";
  version = "0.1.0";
  src = ../.;
  nativeBuildInputs = [ makeWrapper ];
  dontBuild = true;
  installPhase = ''
    mkdir -p "$out/bin" "$out/lib/vcpkg-purifier"
    cp -r vcpkg_purifier nix "$out/lib/vcpkg-purifier/"
    install -m755 bin/vcpkg-purifier "$out/bin/vcpkg-purifier"
    substituteInPlace "$out/lib/vcpkg-purifier/nix/realize.nix" \
      --replace-fail '@nixpkgs@' '${nixpkgsSrc}' \
      --replace-fail '@purifier@' '${purifierSrc}' \
      --replace-fail '@runtime@' "$out"
    wrapProgram "$out/bin/vcpkg-purifier" \
      --prefix PATH : ${
        lib.makeBinPath [
          python3
          nix
          gh
          toolchain
        ]
      } \
      --set-default SSL_CERT_FILE ${cacert}/etc/ssl/certs/ca-bundle.crt \
      --set VCPKG_PURIFIER_NATIVE ${native}/bin/vcpkg \
      --set VCPKG_PURIFIER_NATIVE_ROOT ${native}/share/vcpkg \
      --set VCPKG_PURIFIER_CMAKE ${cmake}/bin/cmake \
      --set VCPKG_PURIFIER_CLANGD ${clang-tools}/bin/clangd \
      --set VCPKG_PURIFIER_TOOLCHAIN ${toolchain} \
      --set VCPKG_PURIFIER_VERSION ${native.version} \
      --set VCPKG_PURIFIER_SYSTEM ${stdenvNoCC.hostPlatform.system}
    for tool in vcpkg cmake clangd; do
      makeWrapper "$out/bin/vcpkg-purifier" "$out/bin/$tool" --add-flags "native $tool --"
    done
    for program in ${toolchain}/bin/*; do
      name=$(basename "$program")
      if [ ! -e "$out/bin/$name" ]; then ln -s "$program" "$out/bin/$name"; fi
    done
  '';
  meta = {
    description = "Native vcpkg workflow with locked Nix-resolved dependencies";
    homepage = "https://nix-purifiers.github.io/";
    license = lib.licenses.mit;
    platforms = [
      "x86_64-linux"
      "aarch64-linux"
    ];
    mainProgram = "vcpkg-purifier";
  };
}
