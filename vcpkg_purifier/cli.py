# SPDX-License-Identifier: MIT
import argparse,fcntl,hashlib,json,os,re,shlex,shutil,subprocess,sys,tempfile
from pathlib import Path
from . import lock,recipes,pins
SYSTEM=os.environ.get('VCPKG_PURIFIER_SYSTEM','x86_64-linux')
NATIVE=os.environ.get('VCPKG_PURIFIER_NATIVE','vcpkg')
GRAPH_ENV=('VCPKG_OVERLAY_PORTS','VCPKG_OVERLAY_TRIPLETS','VCPKG_DEFAULT_TRIPLET','VCPKG_DEFAULT_HOST_TRIPLET','VCPKG_FEATURE_FLAGS')
def native_environment():return {key:value for key,value in os.environ.items() if key not in GRAPH_ENV}
def write(path,text):
 path.parent.mkdir(parents=True,exist_ok=True)
 with tempfile.NamedTemporaryFile('w',dir=path.parent,delete=False) as stream:stream.write(text);temporary=Path(stream.name)
 temporary.replace(path)
def resolver():
 return hashlib.sha256(b''.join(p.read_bytes() for p in sorted(Path(__file__).parent.glob('*.py')))+os.environ['VCPKG_PURIFIER_TOOLCHAIN'].encode()).hexdigest()
def invoke(args,**kwargs):return subprocess.run(list(map(str,args)),check=True,**kwargs)
def native_args(stage,state):return [NATIVE,'--x-manifest-root='+str(stage),'--x-install-root='+str(state/'installed'),'--x-buildtrees-root='+str(state/'buildtrees'),'--x-packages-root='+str(state/'packages'),'--downloads-root='+str(state/'downloads')]
def do_lock(root,native,sidecar,features,update=False,names=()):
 manifest,config,directories=lock.configuration(root);fingerprints=lock.inputs(root,directories)
 previous=None
 if sidecar.is_file():
  try:
   candidate=json.loads(sidecar.read_text())
   if isinstance(candidate,dict) and candidate.get('contentHash')==lock.seal(candidate)['contentHash']:previous=candidate
  except (ValueError,TypeError):pass
 if previous and not update and not lock.problems(root,native,previous,SYSTEM):
  profile=previous['profiles'][SYSTEM]
  if profile.get('resolver')==resolver() and profile['features']==features:
   print('Existing native vcpkg resolution retained',file=sys.stderr);return
 oldprofile=(previous or {}).get('profiles',{}).get(SYSTEM)
 if names and (not oldprofile or any(n not in {p['name'] for p in oldprofile['ports']} for n in names)):raise ValueError('named updates require existing selected ports'+lock.FIX)
 with tempfile.TemporaryDirectory(prefix='vcpkg-purifier-lock-') as temporary:
  temp=Path(temporary);stage=temp/'project';state=temp/'state'
  shutil.copytree(root,stage,ignore=shutil.ignore_patterns('.git','.vcpkg-purifier','vcpkg_installed','build','result','__pycache__'))
  seed=native if native.exists() else root/'vcpkg-lock.json'
  prior=None
  if seed.is_file():
   try:lock.native_pins(seed.read_text());prior=seed.read_text()
   except ValueError:pass
  if prior is None and previous and previous.get('inputs')==fingerprints:
   recovery=previous.get('nativeLock','')
   try:lock.native_pins(recovery);prior=recovery
   except ValueError:pass
  if prior is not None and not update:write(state/'installed/vcpkg/vcpkg-lock.json',prior)
  env={**native_environment(),'TMPDIR':str(temp),'HOME':str(temp/'home'),'XDG_CACHE_HOME':str(temp/'cache'),'VCPKG_DISABLE_METRICS':'1','VCPKG_FORCE_SYSTEM_BINARIES':'1','VCPKG_BINARY_SOURCES':'clear','VCPKG_PURIFIER_INTERNAL':'1','VCPKG_PURIFIER_CAPTURE':str(temp/'assets'),'PYTHONPATH':str(Path(__file__).resolve().parents[1])}
  Path(env['HOME']).mkdir();(temp/'assets').mkdir()
  env['X_VCPKG_ASSET_SOURCES']='clear;x-script,python3 -m vcpkg_purifier.capture "{url}" "{sha512}" "{dst}";x-block-origin'
  args=native_args(stage,state)
  generated=pins.bind(stage,manifest,config,prior,os.environ['VCPKG_PURIFIER_NATIVE_ROOT']) if prior is not None and not update else []
  if update and (manifest.get('builtin-baseline') or 'default-registry' not in config or config.get('default-registry') or config.get('registries')):
   # Use the native updater for registry baseline semantics, including configured Git registries.
   initial=['--add-initial-baseline'] if 'default-registry' not in config and not manifest.get('builtin-baseline') else []
   result=subprocess.run([*args,'x-update-baseline',*initial],cwd=stage,env=env,text=True,stdout=sys.stderr,stderr=sys.stderr)
   if result.returncode:raise ValueError('native registry baseline update failed')
  managed=[]
  if update:
   staged=json.loads((stage/'vcpkg.json').read_text())
   owned=(previous or {}).get('managedOverrides',[])
   overrides=[item for item in staged.get('overrides',[]) if item not in owned]
   if names:
    if directories:raise ValueError('named updates of local overlay/filesystem recipes are not supported; edit them and run lock')
    user_pins={item['name'] for item in overrides}
    for port in oldprofile['ports']:
     if port['name'] in names or port['name'] in user_pins:continue
     version={key:port['manifest'][key] for key in ('version','version-string','version-semver','version-date','port-version') if key in port['manifest']}
     if not any(key.startswith('version') for key in version):raise ValueError('native port has no usable version: '+port['name'])
     managed.append({'name':port['name'],**version})
    overrides+=managed
   if overrides:staged['overrides']=overrides
   else:staged.pop('overrides',None)
   write(stage/'vcpkg.json',json.dumps(staged,indent=2)+'\n')
  else:managed=[item for item in (previous or {}).get('managedOverrides',[]) if item in manifest.get('overrides',[])]
  command=[*args,'install','--triplet='+lock.SYSTEMS[SYSTEM],'--host-triplet='+lock.SYSTEMS[SYSTEM],'--debug',*['--x-feature='+f for f in features]]
  result=subprocess.run(command,cwd=stage,env=env,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
  if result.returncode:
   print(result.stdout,file=sys.stderr);raise ValueError('native vcpkg dependency installation failed')
  selected=recipes.export(result.stdout)
  if manifest.get('dependencies') and not selected:raise ValueError('native vcpkg did not export selected recipes')
  updated_manifest=json.loads((stage/'vcpkg.json').read_text())
  # The runtime repository contains only the selected native recipes. Registry
  # baseline/override decisions have already been applied by the native solver.
  frozen={k:v for k,v in updated_manifest.items() if k not in ('builtin-baseline','configuration','overrides')}
  assets=[]
  oldassets={a['sha512']:a for a in (oldprofile or {}).get('assets',[])}
  for path in sorted((temp/'assets').glob('*.json')):
   asset=json.loads(path.read_text());assets.append(oldassets.get(asset['sha512'],asset))
  profile={'triplet':lock.SYSTEMS[SYSTEM],'features':features,'manifest':frozen,'ports':selected,'assets':assets,'resolver':resolver()}
  native_export=state/'installed/vcpkg/vcpkg-lock.json'
  native_text=native_export.read_text() if native_export.exists() else '{}\n'
  native_text=pins.export(native_text,prior if not update else None,generated)
  lock.native_pins(native_text)
  # External packaging can update its lock without rewriting the working copy's
  # native manifests. Ordinary in-tree updates retain native updater edits.
  if update and sidecar==root/'vcpkg-purifier.lock.json':
   for name in ('vcpkg.json','vcpkg-configuration.json'):
    if (stage/name).exists():write(root/name,(stage/name).read_text())
   manifest,config,directories=lock.configuration(root);fingerprints=lock.inputs(root,directories)
  profiles={}
  if previous and not update and previous.get('inputs')==fingerprints and previous.get('nativeLock')==native_text:profiles.update(previous.get('profiles',{}))
  profiles[SYSTEM]=profile
  data={'version':1,'inputs':fingerprints,'localDirectories':directories,'localIdentities':lock.local_identities(root,directories),'managedOverrides':managed,'nativeLock':native_text,'nativeHash':hashlib.sha256(native_text.encode()).hexdigest(),'profiles':profiles}
  write(native,native_text);write(sidecar,json.dumps(lock.seal(data),sort_keys=True,indent=2,ensure_ascii=False)+'\n')
  print('Locked native vcpkg graph for '+SYSTEM,file=sys.stderr)
def realize(root,native,sidecar,target):
 definition=Path(__file__).resolve().parents[1]/'nix/realize.nix'
 args=['nix','build','--impure','--file',definition,'--argstr','project',root,'--argstr','lockFile',sidecar,'--argstr','vcpkgLock',native,'--argstr','target',target,'--no-link','--print-out-paths']
 return Path(invoke(args,text=True,stdout=subprocess.PIPE).stdout.strip())
def prefetch(root,native,sidecar):
 data=json.loads(sidecar.read_text())
 if problems:=lock.problems(root,native,data,SYSTEM):raise ValueError('\n'.join(problems))
 cache=sidecar.parent/'.vcpkg-purifier'/hashlib.sha256(str(sidecar).encode()).hexdigest()[:16];cache.mkdir(parents=True,exist_ok=True)
 for target in ('environment','runtime'):
  output=realize(root,native,sidecar,target)
  invoke(['nix-store','--add-root',cache/target,'--indirect','--realise',output],stdout=subprocess.DEVNULL)
 return (cache/'environment').resolve()
def publish(root,native,sidecar,repository,tag):
 if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',repository) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._/-]*',tag):raise ValueError('publish requires OWNER/REPOSITORY and a release tag')
 if problems:=lock.problems(root,native,json.loads(sidecar.read_text())):raise ValueError('\n'.join(problems))
 release=realize(root,native,sidecar,'release');gh=os.environ.get('VCPKG_PURIFIER_GH','gh')
 present=subprocess.run([gh,'release','view',tag,'--repo',repository],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode==0
 if present:invoke([gh,'release','upload',tag,'--repo',repository,release/'project.tar.gz','--clobber'])
 else:invoke([gh,'release','create',tag,'--repo',repository,'--title',tag,'--notes','Source release built by Nix.',release/'project.tar.gz'])
def project(arguments,tool):
 candidate=Path.cwd()
 for i,arg in enumerate(arguments):
  if arg in ('-S','--build','--install') and i+1<len(arguments):candidate=Path(arguments[i+1]).expanduser().resolve()
  if arg=='--x-manifest-root' and i+1<len(arguments):candidate=Path(arguments[i+1]).expanduser().resolve()
  if arg.startswith('-S') and len(arg)>2:candidate=Path(arg[2:]).expanduser().resolve()
  if arg.startswith('--x-manifest-root='):candidate=Path(arg.split('=',1)[1]).expanduser().resolve()
 for directory in [candidate,*candidate.parents]:
  if (directory/'vcpkg.json').is_file():return directory
 return candidate
def cmake_arguments(arguments,root,installed,profile):
 result=[];index=0
 while index<len(arguments):
  argument=arguments[index];count=1
  if argument=='-D' and index+1<len(arguments):value=arguments[index+1];count=2
  elif argument.startswith('-D'):value=argument[2:]
  else:result.append(argument);index+=1;continue
  key,separator,content=value.partition('=');key=key.split(':',1)[0]
  managed=key=='CMAKE_TOOLCHAIN_FILE' or key.startswith('VCPKG_')
  if managed:
   if not separator:raise ValueError('missing CMake variable value: '+key)
   if key=='CMAKE_TOOLCHAIN_FILE':
    if not content.endswith('/scripts/buildsystems/vcpkg.cmake'):raise ValueError('custom CMake toolchains need explicit integration; the wrapper supplies the vcpkg toolchain')
   elif key in ('VCPKG_TARGET_TRIPLET','VCPKG_HOST_TRIPLET'):
    if content!=profile['triplet']:raise ValueError('CMake triplet differs from the locked graph'+lock.FIX)
   elif key=='VCPKG_MANIFEST_FEATURES':
    if sorted(filter(None,content.split(';')))!=profile['features']:raise ValueError('CMake features differ from the locked graph'+lock.FIX)
   elif key in ('VCPKG_MANIFEST_DIR','VCPKG_INSTALLED_DIR'):
    expected=root if key=='VCPKG_MANIFEST_DIR' else installed
    if Path(content).expanduser().resolve()!=expected:raise ValueError('the wrapper uses its locked manifest and private installed prefix; remove '+key)
   else:raise ValueError('unsupported locked CMake setting: '+key)
  else:result.extend(arguments[index:index+count])
  index+=count
 return result
def vcpkg_arguments(arguments,root,environment,installed,profile):
 result=[];features=[];index=0
 options={'--triplet','--host-triplet','--x-feature','--vcpkg-root','--x-manifest-root','--x-install-root'}
 while index<len(arguments):
  key,separator,value=arguments[index].partition('=');count=1
  if key not in options:result.append(arguments[index]);index+=1;continue
  if not separator:
   if index+1==len(arguments):raise ValueError('missing native argument value: '+key)
   value=arguments[index+1];count=2
  if key in ('--triplet','--host-triplet') and value!=profile['triplet']:raise ValueError('native triplet differs from the locked graph'+lock.FIX)
  if key=='--x-feature':features.append(value)
  if key=='--x-manifest-root' and Path(value).expanduser().resolve() not in (root,environment/'manifest'):raise ValueError('native manifest root differs from the locked project')
  if key=='--x-install-root' and Path(value).expanduser().resolve()!=installed:raise ValueError('the wrapper uses a private installed prefix; remove --x-install-root')
  index+=count
 if features and sorted(set(features))!=profile['features']:raise ValueError('native features differ from the locked graph'+lock.FIX)
 return [*result,'--x-wait-for-lock','--vcpkg-root='+str(environment/'root'),'--x-manifest-root='+str(environment/'manifest'),'--x-install-root='+str(installed),'--triplet='+profile['triplet'],'--host-triplet='+profile['triplet'],*['--x-feature='+f for f in profile['features']]]
def runtime(root,native,sidecar,tool,arguments):
 command={'vcpkg':NATIVE,'cmake':os.environ['VCPKG_PURIFIER_CMAKE'],'clangd':os.environ['VCPKG_PURIFIER_CLANGD']}[tool]
 if os.environ.get('VCPKG_PURIFIER_INTERNAL')=='1':os.execv(command,[command,*arguments])
 if not sidecar.exists():
  print('vcpkg-purifier: no lockfile; using ordinary impure '+tool,file=sys.stderr);os.execv(command,[command,*arguments])
 environment=prefetch(root,native,sidecar)
 data=json.loads(sidecar.read_text());profile=data['profiles'][SYSTEM]
 if tool=='vcpkg' and any(a.partition('=')[0] in ('--overlay-ports','--overlay-triplets','--head','--classic','--binarysource','--x-asset-sources','--x-no-default-features') for a in arguments):raise ValueError('locked commands use the recorded native graph and source cache; change the project and relock')
 state=root/'.vcpkg-purifier';state.mkdir(exist_ok=True)
 setup=(state/'setup.lock').open('a');fcntl.flock(setup,fcntl.LOCK_EX)
 installed=state/'installed';marker=state/'environment'
 if not marker.exists() or marker.read_text()!=str(environment) or not installed.is_dir():
  staging=state/'installed.new'
  if staging.exists():shutil.rmtree(staging)
  def install_file(source,destination):
   relative=Path(source).relative_to(environment/'installed')
   if relative.parts[0]=='vcpkg':return shutil.copyfile(source,destination)
   Path(destination).symlink_to(source)
  shutil.copytree(environment/'installed',staging,copy_function=install_file,symlinks=True)
  staging.chmod(0o755)
  for directory in staging.rglob('*'):
   if directory.is_dir() and not directory.is_symlink():directory.chmod(0o755)
  if installed.exists():shutil.rmtree(installed)
  staging.replace(installed);write(marker,str(environment))
 setup.close()
 for key in GRAPH_ENV:os.environ.pop(key,None)
 os.environ.update(VCPKG_ROOT=str(environment/'root'),VCPKG_DISABLE_METRICS='1',VCPKG_FORCE_SYSTEM_BINARIES='1',VCPKG_BINARY_SOURCES='clear',VCPKG_PURIFIER_INTERNAL='1',NIX_VCPKG_WRITABLE_PATH=str(state),X_VCPKG_ASSET_SOURCES='clear;x-azurl,file://'+str(environment/'assets')+';x-block-origin')
 if tool=='vcpkg':
  arguments=vcpkg_arguments(arguments,root,environment,installed,profile)
 elif tool=='cmake' and not any(a in ('--build','--install','-P','--version','--help') or a.startswith('--help') for a in arguments):
  arguments=cmake_arguments(arguments,root,installed,profile)
  arguments=[*arguments,'-DCMAKE_TOOLCHAIN_FILE='+str(environment/'root/scripts/buildsystems/vcpkg.cmake'),'-DVCPKG_MANIFEST_DIR='+str(environment/'manifest'),'-DVCPKG_INSTALLED_DIR='+str(installed),'-DVCPKG_TARGET_TRIPLET='+profile['triplet'],'-DVCPKG_HOST_TRIPLET='+profile['triplet'],'-DVCPKG_MANIFEST_FEATURES='+';'.join(profile['features'])]
 os.execv(command,[command,*arguments])
def main():
 parser=argparse.ArgumentParser();parser.add_argument('--project');parser.add_argument('--lockfile',default=os.environ.get('VCPKG_PURIFIER_LOCKFILE'));parser.add_argument('--native-lock',default=os.environ.get('VCPKG_PURIFIER_NATIVE_LOCKFILE'));parser.add_argument('--feature',action='append',default=[])
 sub=parser.add_subparsers(dest='command',required=True);sub.add_parser('lock');p=sub.add_parser('update');p.add_argument('names',nargs='*');sub.add_parser('prefetch');p=sub.add_parser('native');p.add_argument('tool',choices=['vcpkg','cmake','clangd']);p.add_argument('args',nargs=argparse.REMAINDER)
 p=sub.add_parser('publish');p.add_argument('--repo',required=True);p.add_argument('--tag',required=True)
 args=parser.parse_args();arguments=args.args if args.command=='native' else []
 if arguments[:1]==['--']:arguments=arguments[1:]
 root=Path(args.project).expanduser().resolve() if args.project else project(arguments,getattr(args,'tool',None))
 native=Path(args.native_lock).expanduser().resolve() if args.native_lock else root/'vcpkg-lock.json'
 sidecar=Path(args.lockfile).expanduser().resolve() if args.lockfile else root/'vcpkg-purifier.lock.json'
 if args.command in ('lock','update'):do_lock(root,native,sidecar,sorted(set(args.feature)),args.command=='update',getattr(args,'names',[]))
 elif args.command=='prefetch':print(prefetch(root,native,sidecar))
 elif args.command=='publish':publish(root,native,sidecar,args.repo,args.tag)
 else:runtime(root,native,sidecar,args.tool,arguments)
