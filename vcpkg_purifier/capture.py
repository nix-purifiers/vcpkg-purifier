# SPDX-License-Identifier: MIT
"""vcpkg's native x-script asset hook. No CMake source parsing."""
import hashlib,json,os,re,subprocess,sys,tempfile
from pathlib import Path
from .lock import url
def main():
 origin,expected,destination=sys.argv[1:]
 if not url(origin) or not re.fullmatch('[0-9a-f]{128}',expected):raise ValueError('only public HTTP(S), SHA512-tagged assets are supported')
 subprocess.run(['curl','--fail','--location','--silent','--show-error',origin,'--output',destination],check=True)
 if hashlib.sha512(Path(destination).read_bytes()).hexdigest()!=expected:raise ValueError('native vcpkg asset checksum mismatch')
 records=Path(os.environ['VCPKG_PURIFIER_CAPTURE']);records.mkdir(parents=True,exist_ok=True)
 with tempfile.NamedTemporaryFile('w',dir=records,delete=False) as output:
  json.dump({'url':origin,'sha512':expected},output);temporary=Path(output.name)
 temporary.replace(records/(expected+'.json'))
if __name__=='__main__':main()
