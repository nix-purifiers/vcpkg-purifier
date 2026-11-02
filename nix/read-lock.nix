# SPDX-License-Identifier: MIT
{ lib }:
{
  src,
  lockFile ? src + "/vcpkg-purifier.lock.json",
  vcpkgLock ? src + "/vcpkg-lock.json",
}:
let
  fix = message: "vcpkg-purifier: ${message}; run vcpkg-purifier lock";
  exists = builtins.pathExists lockFile && builtins.pathExists vcpkgLock;
  raw =
    if exists then
      builtins.addErrorContext (fix "invalid companion JSON") (
        builtins.fromJSON (builtins.readFile lockFile)
      )
    else
      { };
  data = if builtins.isAttrs raw then raw else { };
  native = if exists then builtins.readFile vcpkgLock else "{}";
  pins = builtins.addErrorContext (fix "invalid native registry JSON") (builtins.fromJSON native);
  systems = {
    x86_64-linux = "x64-linux";
    aarch64-linux = "arm64-linux";
  };
  nameOK = v: builtins.isString v && builtins.match "[a-z0-9][a-z0-9-]*" v != null;
  pathOK =
    v:
    builtins.isString v
    && v != ""
    && !lib.hasPrefix "/" v
    && !lib.hasInfix "\\" v
    && builtins.all (
      p:
      !(builtins.elem p [
        ""
        "."
        ".."
      ])
    ) (lib.splitString "/" v);
  hex = n: v: builtins.isString v && builtins.match "[0-9a-f]{${toString n}}" v != null;
  urlOK = v: builtins.isString v && builtins.match "https?://[^/@[:space:]]+/[^[:space:]]*" v != null;
  list = builtins.isList;
  unique = xs: builtins.length xs == builtins.length (lib.unique xs);
  fileOK =
    f:
    builtins.isAttrs f
    && pathOK (f.path or null)
    && builtins.isBool (f.executable or null)
    && builtins.isString (f.contents or null)
    && builtins.match "([A-Za-z0-9+/]{4})*([A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?" f.contents != null;
  portOK =
    p:
    builtins.isAttrs p
    && nameOK (p.name or null)
    && builtins.isAttrs (p.manifest or null)
    && list (p.files or null)
    && builtins.all fileOK p.files
    && unique (map (f: f.path) p.files)
    && builtins.all (name: builtins.elem name (map (f: f.path) p.files)) [
      "vcpkg.json"
      "portfile.cmake"
    ];
  assetOK = a: builtins.isAttrs a && urlOK (a.url or null) && hex 128 (a.sha512 or null);
  profileOK =
    system: p:
    builtins.hasAttr system systems
    && builtins.isAttrs p
    && hex 64 (p.resolver or null)
    && (p.triplet or null) == systems.${system}
    && builtins.isAttrs (p.manifest or null)
    && list (p.features or null)
    && builtins.all nameOK p.features
    && list (p.ports or null)
    && builtins.all portOK p.ports
    && unique (map (v: v.name) p.ports)
    && list (p.assets or null)
    && builtins.all assetOK p.assets
    && unique (map (v: v.sha512) p.assets);
  directories = data.localDirectories or null;
  walk =
    prefix: directory:
    lib.concatMap (
      name:
      let
        path = if prefix == "" then name else "${prefix}/${name}";
        kind = (builtins.readDir directory).${name};
      in
      if name == ".git" then
        [ ]
      else if kind == "directory" then
        walk path (directory + "/${name}")
      else
        [
          {
            inherit path;
            hash = if kind == "regular" then builtins.hashFile "sha256" (directory + "/${name}") else null;
          }
        ]
    ) (builtins.attrNames (builtins.readDir directory));
  inputPaths = [
    "vcpkg.json"
    "vcpkg-configuration.json"
  ];
  currentInputs = builtins.sort (a: b: a.path < b.path) (
    map (path: {
      inherit path;
      hash =
        if builtins.pathExists (src + "/${path}") then
          builtins.hashFile "sha256" (src + "/${path}")
        else
          null;
    }) inputPaths
    ++ lib.concatMap (directory: walk directory (src + "/${directory}")) directories
  );
  localIdentities = map (directory: {
    path = directory;
    storePath = toString (
      builtins.path {
        path = src + "/${directory}";
        name = "vcpkg-local-input";
        filter = path: type: baseNameOf path != ".git";
      }
    );
  }) directories;
  problems =
    if !exists then
      [ (fix "missing native or companion lock") ]
    else if !builtins.isAttrs raw || (data.version or null) != 1 then
      [ (fix "unsupported companion format") ]
    else if
      (data.contentHash or null)
      != builtins.hashString "sha256" (builtins.toJSON (removeAttrs data [ "contentHash" ]))
    then
      [ (fix "companion contentHash mismatch") ]
    else if
      !builtins.isAttrs pins
      || !builtins.all (refs: builtins.isAttrs refs && builtins.all (hex 40) (builtins.attrValues refs)) (
        builtins.attrValues pins
      )
    then
      [ (fix "invalid native registry pins") ]
    else if
      (data.nativeHash or null) != builtins.hashString "sha256" native
      || (data.nativeLock or null) != native
    then
      [ (fix "native registry lock changed") ]
    else if !list directories || !builtins.all pathOK directories || !unique directories then
      [ (fix "invalid local registry inputs") ]
    else if !builtins.all (directory: builtins.pathExists (src + "/${directory}/.")) directories then
      [ (fix "missing local registry input") ]
    else if (data.inputs or null) != currentInputs then
      [ (fix "vcpkg project configuration changed") ]
    else if (data.localIdentities or null) != localIdentities then
      [ (fix "local registry contents or executable modes changed") ]
    else if
      !builtins.isAttrs (data.profiles or null)
      || data.profiles == { }
      || !builtins.all (system: profileOK system data.profiles.${system}) (
        builtins.attrNames data.profiles
      )
    then
      [ (fix "invalid native platform graph export") ]
    else
      [ ];
  entries =
    if problems != [ ] then
      [ ]
    else
      lib.concatMap (
        system:
        let
          profile = data.profiles.${system};
          prefix = "systems/${system}";
        in
        map (a: {
          path = "${prefix}/assets/${a.sha512}";
          inherit (a) url;
          mirrors = [ ];
          hash = builtins.convertHash {
            hash = a.sha512;
            hashAlgo = "sha512";
            toHashFormat = "sri";
          };
          systems = [ system ];
        }) profile.assets
        ++ lib.concatMap (
          port:
          map (file: {
            path = "${prefix}/encoded/${port.name}/${file.path}";
            contents = file.contents;
            systems = [ system ];
          }) port.files
        ) profile.ports
      ) (builtins.attrNames data.profiles);
in
{
  purifier = "vcpkg-purifier";
  inherit entries problems data;
  outputs =
    if problems != [ ] then
      { }
    else
      {
        project = { };
        environment = { };
      };
}
