# SPDX-License-Identifier: MIT
"""Bind native registry references to saved revisions before a cold-cache run."""
import copy,json
from pathlib import Path
from .lock import native_pins
BUILTIN='https://github.com/microsoft/vcpkg'
def bind(stage,manifest,configuration,prior,native_root):
 saved=native_pins(prior);config=copy.deepcopy(configuration);manifest=copy.deepcopy(manifest)
 default=config.get('default-registry',{'kind':'builtin'})
 if default is not None and default.get('kind')=='builtin' and BUILTIN in saved:
  bundle=json.loads((Path(native_root)/'vcpkg-bundle.json').read_text())
  baseline=manifest.pop('builtin-baseline',None) or default.get('baseline') or bundle['embeddedsha']
  config['default-registry']={'kind':'git','repository':BUILTIN,'baseline':baseline}
 generated=[]
 for registry in [config.get('default-registry'),*config.get('registries',[])]:
  if registry is None or registry.get('kind')!='git':continue
  repository=registry['repository'];reference=registry.get('reference','HEAD')
  revision=saved.get(repository,{}).get(reference)
  if revision is None:continue
  registry['reference']=revision
  if revision not in saved[repository]:generated.append((repository,revision))
 manifest.pop('configuration',None)
 (stage/'vcpkg.json').write_text(json.dumps(manifest,indent=2)+'\n')
 (stage/'vcpkg-configuration.json').write_text(json.dumps(config,indent=2)+'\n')
 return generated
def export(text,prior,generated):
 data=native_pins(text)
 for repository,reference in generated:
  if repository in data:data[repository].pop(reference,None)
 if prior is not None and data==native_pins(prior):return prior
 return json.dumps(data,indent=2)+'\n'
