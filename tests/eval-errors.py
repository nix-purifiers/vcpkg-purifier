#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
import copy,json,shutil,subprocess,sys,tempfile
from pathlib import Path
REPO=Path(__file__).resolve().parents[1];sys.path.insert(0,str(REPO))
from vcpkg_purifier import lock
with tempfile.TemporaryDirectory(prefix='vcpkg-invalid-') as temporary:
 root=Path(temporary)/'project';shutil.copytree(REPO/'examples/minimal',root,ignore=shutil.ignore_patterns('build','.vcpkg-purifier','*.log'))
 sidecar=root/'vcpkg-purifier.lock.json';native=root/'vcpkg-lock.json';manifest=root/'vcpkg.json'
 original=sidecar.read_text();native_original=native.read_text();manifest_original=manifest.read_text();data=json.loads(original)
 expression='let f=builtins.getFlake '+json.dumps(str(REPO))+'; in (f.lib.vcpkg-purifier.readLock {src=/. + '+json.dumps(str(root))+';}).problems'
 def evaluate(invalid):
  result=subprocess.run(['nix','eval','--impure','--json','--expr',expression],text=True,capture_output=True)
  if result.returncode:assert invalid and 'vcpkg-purifier' in result.stderr,result.stderr
  else:assert bool(json.loads(result.stdout))==invalid,result.stdout
 evaluate(False)
 for mutation in ('hash','asset','recipe','profile','features','native-pin','configuration','scalar','malformed'):
  changed=copy.deepcopy(data);profile=next(iter(changed['profiles'].values()))
  if mutation=='hash':changed['contentHash']='bad'
  elif mutation=='asset':profile['assets'][0]['url']='https://user:password@example.invalid/archive';changed=lock.seal(changed)
  elif mutation=='recipe':profile['ports'][0]['files'][0]['path']='../../escape';changed=lock.seal(changed)
  elif mutation=='profile':profile.pop('triplet');changed=lock.seal(changed)
  elif mutation=='features':profile['features']=3;changed=lock.seal(changed)
  elif mutation=='native-pin':
   native.write_text('{"https://example.invalid/registry":{"HEAD":"bad"}}');changed['nativeHash']=lock.digest(native);changed['nativeLock']=native.read_text();changed=lock.seal(changed)
  elif mutation=='configuration':manifest.write_text(manifest_original+'\n')
  elif mutation=='scalar':changed=3
  if mutation=='malformed':sidecar.write_text('invalid JSON')
  else:sidecar.write_text(json.dumps(changed))
  evaluate(True);native.write_text(native_original);manifest.write_text(manifest_original);sidecar.write_text(original)
 sidecar.unlink();evaluate(True)
print('PASS invalid-lock evaluation')
