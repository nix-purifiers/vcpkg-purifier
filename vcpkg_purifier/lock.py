# SPDX-License-Identifier: MIT
"""Validate native registry pins and the portable source/recipe export."""
import base64,hashlib,json,re,shutil,subprocess,tempfile
from pathlib import Path
from urllib.parse import urlsplit
FIX='; run vcpkg-purifier lock'
NAME=r'[a-z0-9][a-z0-9-]*'
SYSTEMS={'x86_64-linux':'x64-linux','aarch64-linux':'arm64-linux'}
def canonical(data):return json.dumps(data,sort_keys=True,separators=(',',':'),ensure_ascii=False)
def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def seal(data):
 result={k:v for k,v in data.items() if k!='contentHash'}
 return {**result,'contentHash':hashlib.sha256(canonical(result).encode()).hexdigest()}
def relative(value):
 return isinstance(value,str) and bool(value) and not value.startswith('/') and all(p not in ('','.','..') for p in value.split('/')) and '\\' not in value
def url(value):
 if not isinstance(value,str):return False
 p=urlsplit(value)
 return p.scheme in ('http','https') and bool(p.hostname) and p.username is None and p.password is None and not any(c.isspace() for c in value)
def native_pins(text):
 data=json.loads(text)
 if not isinstance(data,dict):raise ValueError('invalid native registry lock'+FIX)
 for repository,refs in data.items():
  # File Git registries are useful for local development; exported recipes are
  # portable, while the source project remains responsible for that registry.
  if not isinstance(repository,str) or not isinstance(refs,dict):raise ValueError('invalid native registry lock'+FIX)
  if any(not isinstance(ref,str) or not isinstance(rev,str) or not re.fullmatch('[0-9a-f]{40}',rev) for ref,rev in refs.items()):raise ValueError('invalid native registry revision'+FIX)
 return data
def configuration(root):
 manifest=json.loads((root/'vcpkg.json').read_text())
 cfgpath=root/'vcpkg-configuration.json'
 config=json.loads(cfgpath.read_text()) if cfgpath.exists() else manifest.get('configuration',{})
 if not isinstance(manifest,dict) or not isinstance(config,dict):raise ValueError('expected native vcpkg manifest/configuration objects')
 if config.get('overlay-triplets'):raise ValueError('custom triplets need a separately supplied toolchain; not supported yet')
 directories=[]
 for path in config.get('overlay-ports',[]):
  if not relative(path):raise ValueError('overlay ports must be relative to the project root')
  directories.append(path)
 for registry in [config.get('default-registry'),*config.get('registries',[])]:
  if registry is None:continue
  if not isinstance(registry,dict) or registry.get('kind') not in ('builtin','git','filesystem'):raise ValueError('unsupported vcpkg registry kind')
  if registry['kind']=='filesystem':
   path=registry.get('path')
   if not relative(path):raise ValueError('filesystem registries must be relative to the project root')
   directories.append(path)
 for directory in directories:
  if not (root/directory).resolve().is_relative_to(root.resolve()):raise ValueError('local registry escapes the project root')
 return manifest,config,sorted(set(directories))
def inputs(root,directories):
 paths={Path('vcpkg.json'),Path('vcpkg-configuration.json')}
 for directory in directories:
  base=root/directory
  if not base.is_dir():raise ValueError('missing local registry/overlay '+directory)
  for path in base.rglob('*'):
   if '.git' in path.relative_to(base).parts:continue
   if path.is_symlink():raise ValueError('symlinks in local registry inputs are not supported yet: '+str(path))
   if path.is_file():paths.add(path.relative_to(root))
 return [{'path':str(p),'hash':digest(root/p) if (root/p).is_file() else None} for p in sorted(paths)]
def local_identities(root,directories):
 result=[]
 for directory in directories:
  with tempfile.TemporaryDirectory(prefix='vcpkg-local-input-') as temporary:
   source=Path(temporary)/'source';shutil.copytree(root/directory,source,ignore=shutil.ignore_patterns('.git'))
   identity=subprocess.run(['nix','store','add-path','--name','vcpkg-local-input',str(source)],text=True,stdout=subprocess.PIPE,check=True).stdout.strip()
   result.append({'path':directory,'storePath':identity})
 return result
def problems(root,native,data,system=None):
 try:
  if not isinstance(data,dict) or data.get('version')!=1:return ['unsupported companion format'+FIX]
  if data.get('contentHash')!=seal(data)['contentHash']:return ['companion contentHash mismatch'+FIX]
  native_pins(native.read_text())
  if digest(native)!=data.get('nativeHash') or native.read_text()!=data.get('nativeLock'):return ['native registry lock changed'+FIX]
  manifest,config,directories=configuration(root)
  if directories!=data.get('localDirectories') or inputs(root,directories)!=data.get('inputs'):return ['vcpkg project configuration changed'+FIX]
  if local_identities(root,directories)!=data.get('localIdentities'):return ['local registry contents or executable modes changed'+FIX]
  if not isinstance(data.get('profiles'),dict) or not data['profiles']:return ['missing native platform profiles'+FIX]
  if system and system not in data['profiles']:return ['no locked dependency graph for '+system+FIX]
  for platform,profile in data['profiles'].items():
   if platform not in SYSTEMS or not isinstance(profile,dict) or profile.get('triplet')!=SYSTEMS[platform]:raise ValueError('invalid platform profile')
   if not isinstance(profile.get('resolver'),str) or not re.fullmatch('[0-9a-f]{64}',profile['resolver']):raise ValueError('invalid native resolver identity')
   if not isinstance(profile.get('features'),list) or any(not isinstance(f,str) or not re.fullmatch(NAME,f) for f in profile['features']):raise ValueError('invalid native features')
   if not isinstance(profile.get('manifest'),dict) or not isinstance(profile.get('ports'),list) or not isinstance(profile.get('assets'),list):raise ValueError('missing native graph export')
   names=set()
   for port in profile['ports']:
    if not isinstance(port,dict) or not isinstance(port.get('name'),str) or not re.fullmatch(NAME,port['name']) or port['name'] in names:raise ValueError('invalid or duplicate port')
    names.add(port['name'])
    if not isinstance(port.get('files'),list) or not port['files']:raise ValueError('missing native port recipe')
    paths=set()
    for item in port['files']:
     if not isinstance(item,dict) or not relative(item.get('path')) or item['path'] in paths or not isinstance(item.get('executable'),bool):raise ValueError('invalid recipe file')
     paths.add(item['path']);base64.b64decode(item['contents'],validate=True)
    if 'portfile.cmake' not in paths or 'vcpkg.json' not in paths:raise ValueError('missing native recipe manifest')
   assets=set()
   for asset in profile['assets']:
    if not isinstance(asset,dict) or not url(asset.get('url')) or not isinstance(asset.get('sha512'),str) or not re.fullmatch('[0-9a-f]{128}',asset['sha512']) or asset['sha512'] in assets:raise ValueError('invalid or duplicate source asset')
    assets.add(asset['sha512'])
  return []
 except (OSError,ValueError,TypeError,KeyError,AttributeError) as error:return [str(error)+FIX]
