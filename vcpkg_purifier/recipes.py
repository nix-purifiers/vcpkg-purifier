# SPDX-License-Identifier: MIT
"""Export the recipes actually selected by native vcpkg's transaction."""
import base64,json,re,shlex
from pathlib import Path
def export(log):
 ports={}
 for line in log.splitlines():
  if 'execute_process(' not in line or '-DCURRENT_PORT_DIR=' not in line or '-DPORT=' not in line:continue
  command=line.split('execute_process(',1)[1].rstrip()
  if command.endswith(')'):command=command[:-1]
  args=shlex.split(command);values={}
  for arg in args:
   if arg.startswith('-D') and '=' in arg:
    name,value=arg[2:].split('=',1);values[name]=value
  if not re.fullmatch('[a-z0-9][a-z0-9-]*',values.get('PORT','')):raise ValueError('invalid native port name')
  directory=Path(values['CURRENT_PORT_DIR'])
  if not (directory/'vcpkg.json').is_file():raise ValueError('legacy CONTROL recipes are not supported yet: '+values['PORT'])
  manifest=json.loads((directory/'vcpkg.json').read_text())
  files=[]
  for path in sorted(directory.rglob('*')):
   if path.is_symlink():raise ValueError('recipe symlinks need explicit export support: '+str(path))
   if path.is_file():files.append({'path':str(path.relative_to(directory)),'contents':base64.b64encode(path.read_bytes()).decode(),'executable':bool(path.stat().st_mode&0o111)})
  record={'name':values['PORT'],'manifest':manifest,'files':files}
  if values['PORT'] in ports and ports[values['PORT']]!=record:raise ValueError('different host and target recipes for one port are not supported yet')
  ports[values['PORT']]=record
 return [ports[name] for name in sorted(ports)]
def materialize(ports,destination):
 for port in ports:
  for item in port['files']:
   path=destination/port['name']/item['path'];path.parent.mkdir(parents=True,exist_ok=True)
   path.write_bytes(base64.b64decode(item['contents'],validate=True));path.chmod(0o755 if item['executable'] else 0o644)
