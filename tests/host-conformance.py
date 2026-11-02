#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Real vcpkg Git registry, versioned recipes, HTTP assets and ordinary tools."""
import functools,gzip,hashlib,http.server,io,json,os,shutil,subprocess,sys,tarfile,tempfile,threading
from pathlib import Path
REPO=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(REPO))
from vcpkg_purifier import recipes
def run(args,**kwargs):
 try:return subprocess.run(list(map(str,args)),check=True,text=True,**kwargs)
 except subprocess.CalledProcessError as error:
  if error.stdout:print(error.stdout,file=sys.stderr)
  if error.stderr:print(error.stderr,file=sys.stderr)
  raise
case=sys.argv[1]
with tempfile.TemporaryDirectory(prefix='vcpkg-conformance-') as temporary:
 temp=Path(temporary);cli=temp/'cli';run(['nix','build',str(REPO)+'#cli','--out-link',cli])
 purifier=cli/'bin/vcpkg-purifier';cmake=cli/'bin/cmake'
 root=temp/'project';root.mkdir();registry=temp/'registry';registry.mkdir();served=temp/'assets';served.mkdir()
 run(['git','init','-b','main',registry],capture_output=True)
 def git(*args):return run(['git','-C',registry,*args],capture_output=True).stdout.strip()
 def commit(message):
  git('add','ports','versions') if (registry/'versions').exists() else git('add','ports')
  git('-c','user.name=purifier-test','-c','user.email=purifier-test@example.invalid','commit','-m',message)
 class Quiet(http.server.SimpleHTTPRequestHandler):
  def log_message(self,*_):pass
 server=http.server.ThreadingHTTPServer(('127.0.0.1',0),functools.partial(Quiet,directory=served))
 worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
 versions={name:[] for name in ('first','second')}
 def release(name,version,value):
  archive=served/(name+'-'+version+'.tar.gz')
  with archive.open('wb') as raw,gzip.GzipFile(fileobj=raw,mode='wb',mtime=0) as compressed,tarfile.open(fileobj=compressed,mode='w') as tar:
   for filename,contents in [(name+'.h','#define '+name.upper()+'_VALUE "'+value+'"\n'),('LICENSE','Test fixture, MIT\n')]:
    data=contents.encode();info=tarfile.TarInfo(name+'-'+version+'/'+filename);info.size=len(data);info.mtime=1;tar.addfile(info,io.BytesIO(data))
  port=registry/'ports'/name;port.mkdir(parents=True,exist_ok=True)
  (port/'vcpkg.json').write_text(json.dumps({'name':name,'version-string':version,'description':'Native purifier fixture','license':'MIT'}))
  (port/'portfile.cmake').write_text('vcpkg_download_distfile(ARCHIVE URLS "http://127.0.0.1:'+str(server.server_port)+'/'+archive.name+'" FILENAME "'+archive.name+'" SHA512 '+hashlib.sha512(archive.read_bytes()).hexdigest()+')\nvcpkg_extract_source_archive(SOURCE_PATH ARCHIVE "${ARCHIVE}")\nfile(INSTALL "${SOURCE_PATH}/'+name+'.h" DESTINATION "${CURRENT_PACKAGES_DIR}/include")\nfile(INSTALL "${SOURCE_PATH}/LICENSE" DESTINATION "${CURRENT_PACKAGES_DIR}/share/${PORT}" RENAME copyright)\n')
 def metadata(version):
  for name in versions:
   tree=git('rev-parse','HEAD:ports/'+name);versions[name].insert(0,{'git-tree':tree,'version-string':version,'port-version':0})
   path=registry/'versions'/(name[0]+'-')/(name+'.json');path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps({'versions':versions[name]}))
  (registry/'versions/baseline.json').write_text(json.dumps({'default':{name:{'baseline':version,'port-version':0} for name in versions}}))
  commit('native version registry '+version)
 try:
  for name in versions:release(name,'1.0','one')
  commit('ports 1');metadata('1.0');baseline=git('rev-parse','HEAD')
  (root/'vcpkg.json').write_text(json.dumps({'name':'consumer','version-string':'1.0','dependencies':['first','second']}))
  (root/'vcpkg-configuration.json').write_text(json.dumps({'default-registry':{'kind':'git','repository':registry.as_uri(),'baseline':baseline}}))
  (root/'main.c').write_text('#include <stdio.h>\n#include <first.h>\n#include <second.h>\nint main(void) {puts(FIRST_VALUE "-" SECOND_VALUE);return 0;}\n')
  (root/'CMakeLists.txt').write_text('cmake_minimum_required(VERSION 3.20)\nproject(consumer C)\nfind_path(FIRST_INCLUDE first.h REQUIRED)\nfind_path(SECOND_INCLUDE second.h REQUIRED)\nadd_executable(consumer main.c)\ntarget_include_directories(consumer PRIVATE "${FIRST_INCLUDE}" "${SECOND_INCLUDE}")\ninstall(TARGETS consumer RUNTIME DESTINATION bin)\n')
  args=[purifier,'--project',root];native=root/'vcpkg-lock.json';sidecar=root/'vcpkg-purifier.lock.json'
  run([*args,'lock']);initial=sidecar.read_bytes();native_initial=native.read_bytes();config_initial=(root/'vcpkg-configuration.json').read_bytes()
  run([*args,'lock']);assert sidecar.read_bytes()==initial and native.read_bytes()==native_initial
  for name in versions:release(name,'2.0','two')
  commit('ports 2');metadata('2.0')
  run([*args,'lock']);assert sidecar.read_bytes()==initial
  expected='one-one';selected=sidecar
  if case=='update':
   run([*args,'update','first']);expected='two-one'
   data=json.loads(sidecar.read_text());profile=next(iter(data['profiles'].values()))
   chosen={p['name']:p['manifest']['version-string'] for p in profile['ports']};assert chosen=={'first':'2.0','second':'1.0'},chosen
   run([*args,'update']);expected='two-two'
  elif case=='relock':
   damaged=json.loads(initial);damaged['contentHash']='bad';sidecar.write_text(json.dumps(damaged));run([*args,'lock'])
   profile=next(iter(json.loads(sidecar.read_text())['profiles'].values()));assert {p['manifest']['version-string'] for p in profile['ports']}=={'1.0'}
   native.write_text('invalid native JSON');run([*args,'lock']);assert native.read_bytes()==native_initial
  elif case=='external':
   selected=temp/'external/companion.json';external_native=temp/'external/native.json'
   args=[purifier,'--project',root,'--lockfile',selected,'--native-lock',external_native]
   run([*args,'lock']);assert native.read_bytes()==native_initial and sidecar.read_bytes()==initial and (root/'vcpkg-configuration.json').read_bytes()==config_initial
   sidecar.unlink();native.unlink()
   os.environ['VCPKG_PURIFIER_LOCKFILE']=str(selected);os.environ['VCPKG_PURIFIER_NATIVE_LOCKFILE']=str(external_native)
  elif case=='local':
   data=json.loads(initial);profile=next(iter(data['profiles'].values()))
   recipes.materialize(profile['ports'],root/'overlays')
   (root/'vcpkg-configuration.json').write_text(json.dumps({'default-registry':None,'overlay-ports':['overlays']}))
   run([*args,'lock'])
   script=root/'overlays/first/portfile.cmake';script.chmod(0o755)
   changed=subprocess.run([str(cmake),'--version'],cwd=root,text=True,capture_output=True)
   assert changed.returncode and 'executable modes changed' in changed.stderr,changed.stderr
   expression='let f=builtins.getFlake '+json.dumps(str(REPO))+'; in (f.lib.vcpkg-purifier.readLock {src=/. + '+json.dumps(str(root))+';}).problems'
   assert json.loads(run(['nix','eval','--impure','--json','--expr',expression],capture_output=True).stdout)
   script.chmod(0o644)
   extra=root/'overlays/first/new-file';extra.write_text('new input')
   changed=subprocess.run([str(cmake),'--version'],cwd=root,text=True,capture_output=True);assert changed.returncode
   extra.unlink()
  environment=Path(run([*args,'prefetch'],capture_output=True).stdout.strip())
  server.shutdown();server.server_close();worker.join()
  profile=next(iter(json.loads(selected.read_text())['profiles'].values()))
  run([cmake,'-S',root,'-B',root/'build','-DCMAKE_EXPORT_COMPILE_COMMANDS=ON','-DCMAKE_TOOLCHAIN_FILE='+str(environment/'root/scripts/buildsystems/vcpkg.cmake'),'-D','VCPKG_TARGET_TRIPLET='+profile['triplet']],cwd=root,env={**os.environ,'VCPKG_OVERLAY_PORTS':str(temp/'untracked-overlay')})
  run([cmake,'--build',root/'build'],cwd=root)
  output=run([root/'build/consumer'],capture_output=True).stdout.strip();assert output==expected,output
  editor=run([cli/'bin/clangd','--check='+str(root/'main.c'),'--compile-commands-dir='+str(root/'build'),'--header-insertion=never'],cwd=root,capture_output=True)
  assert '0 errors' in editor.stderr,editor.stderr
  if case=='native':
   run([cli/'bin/vcpkg','install','--triplet',profile['triplet']],cwd=root,capture_output=True)
   # Exercise the actual Nix source release through a local gh double; never
   # create an external test release or upload application sources.
   gh=temp/'gh';ghlog=temp/'gh.jsonl';ghstate=temp/'published'
   gh.write_text('#!'+str((cli/'bin/python3').resolve())+'\nimport json,os,sys,tarfile\nfrom pathlib import Path\na=sys.argv[1:]\nwith open(os.environ["TEST_GH_LOG"],"a") as f:f.write(json.dumps(a)+"\\n")\nstate=Path(os.environ["TEST_GH_STATE"])\nif a[1]=="view":raise SystemExit(0 if state.exists() else 1)\narchive=next(Path(v) for v in a if v.endswith("project.tar.gz"))\nwith tarfile.open(archive) as tar:\n assert "./vcpkg-purifier.lock.json" in tar.getnames()\n assert "./vcpkg-lock.json" in tar.getnames()\nstate.touch()\n')
   gh.chmod(0o755)
   publish_env={**os.environ,'VCPKG_PURIFIER_GH':str(gh),'TEST_GH_LOG':str(ghlog),'TEST_GH_STATE':str(ghstate)}
   for _ in range(2):run([*args,'publish','--repo','example/project','--tag','v1.0.0'],env=publish_env)
   operations=[json.loads(line)[1] for line in ghlog.read_text().splitlines()];assert operations==['view','create','view','upload'],operations
   manifest=root/'vcpkg.json';before=manifest.read_text();manifest.write_text(before+'\n')
   stale=subprocess.run([str(cmake),'--build',str(root/'build')],cwd=root,text=True,capture_output=True);assert stale.returncode and 'ordinary impure' not in stale.stderr
   manifest.write_text(before);sidecar.unlink()
   fallback=run([cmake,'--version'],cwd=root,capture_output=True);assert 'ordinary impure cmake' in fallback.stderr
   failure=root/'fail.cmake';failure.write_text('message(FATAL_ERROR "native failure")\n')
   failed=subprocess.run([str(cmake),'-P',str(failure)],cwd=root,text=True,capture_output=True);assert failed.returncode==1 and 'native failure' in failed.stderr
 finally:
  if worker.is_alive():server.shutdown();server.server_close();worker.join()
print('PASS '+case)
