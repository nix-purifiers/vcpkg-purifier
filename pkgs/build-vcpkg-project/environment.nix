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
}:
{
  lock,
  fetchers ? { },
}:
let
  checked = purifier.checkLock lock;
  system = toolchain.system;
  profile =
    checked.data.profiles.${system}
      or (throw "vcpkg-purifier: no locked graph for ${system}; run vcpkg-purifier lock on that platform");
  sources = purifier.tree (
    {
      inherit runCommand fetchurl;
      name = "vcpkg-locked-sources";
      entries = builtins.filter (entry: builtins.elem system entry.systems) checked.entries;
    }
    // fetchers
  );
  metadata = writeText "vcpkg-native-profile.json" (builtins.toJSON profile);
  prepare = writeText "vcpkg-prepare.py" ''
    import base64,json,os,sys
    from pathlib import Path
    source,out=map(Path,sys.argv[1:])
    profile=json.loads(Path('${metadata}').read_text())
    out.mkdir(exist_ok=True)
    (out/'ports').mkdir()
    for port in profile['ports']:
     for file in port['files']:
      target=out/'ports'/port['name']/file['path']
      target.parent.mkdir(parents=True,exist_ok=True)
      encoded=source/'systems/${system}/encoded'/port['name']/file['path']
      target.write_bytes(base64.b64decode(encoded.read_text(),validate=True))
      target.chmod(0o755 if file['executable'] else 0o644)
    assets=source/'systems/${system}/assets'
    if assets.exists():(out/'assets').symlink_to(assets)
    else:(out/'assets').mkdir()
    (out/'manifest').mkdir()
    (out/'manifest/vcpkg.json').write_text(json.dumps(profile['manifest']))
    (out/'manifest/vcpkg-configuration.json').write_text(json.dumps({'default-registry':None,'overlay-ports':[str(out/'ports')]}))
    (out/'metadata.json').write_text(json.dumps({'triplet':profile['triplet'],'features':profile['features']}))
  '';
  normalize = writeText "vcpkg-normalize-spdx.py" ''
    import json,sys,uuid
    from pathlib import Path
    for path in Path(sys.argv[1]).rglob('vcpkg.spdx.json'):
     data=json.loads(path.read_text())
     if 'creationInfo' in data:data['creationInfo']['created']='1970-01-01T00:00:01Z'
     namespace=data.pop('documentNamespace',None)
     if namespace is not None:data['documentNamespace']=namespace[:-36]+str(uuid.uuid5(uuid.NAMESPACE_URL,json.dumps(data,sort_keys=True,separators=(',',':'))))
     path.write_text(json.dumps(data,sort_keys=True,indent=2)+'\n')
  '';
in
runCommand "purified-vcpkg-environment"
  {
    nativeBuildInputs = [
      toolchain
      python3
    ];
  }
  ''
        export HOME="$TMPDIR/home"
        export XDG_CACHE_HOME="$TMPDIR/cache"
        export VCPKG_DISABLE_METRICS=1
        export VCPKG_FORCE_SYSTEM_BINARIES=1
        export VCPKG_BINARY_SOURCES=clear
    unset VCPKG_OVERLAY_PORTS VCPKG_OVERLAY_TRIPLETS VCPKG_FEATURE_FLAGS
        export NIX_VCPKG_WRITABLE_PATH="$TMPDIR/vcpkg"
        mkdir -p "$HOME"
        python3 ${prepare} ${sources} "$out"
        mkdir -p "$out/root"
        for name in scripts triplets versions docs LICENSE.txt .vcpkg-root; do ln -s ${native}/share/vcpkg/"$name" "$out/root/$name"; done
        ln -s "$out/ports" "$out/root/ports"
        ln -s ${native}/bin/vcpkg "$out/root/vcpkg"
        echo '{"readonly":true,"usegitregistry":false,"deployment":"Git"}' > "$out/root/vcpkg-bundle.json"
        export VCPKG_ROOT="$out/root"
        export X_VCPKG_ASSET_SOURCES="clear;x-azurl,file://$out/assets;x-block-origin"
        vcpkg install --vcpkg-root="$out/root" --x-manifest-root="$out/manifest" \
          --x-install-root="$out/installed" --triplet=${profile.triplet} --host-triplet=${profile.triplet} \
          ${lib.concatMapStringsSep " " (
            feature: lib.escapeShellArg "--x-feature=${feature}"
          ) profile.features}
        # Native SPDX documents contain a wall-clock creation time and a random
        # document UUID. Preserve their dependency/licensing data and stabilize only
        # these generated fields.
        python3 ${normalize} "$out/installed"
  ''
