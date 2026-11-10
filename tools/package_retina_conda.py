"""Package the verified upstream wheel for conda (PyTorch runtime variant).
No pip installation, source modification, or dependency download is performed.
Usage: conda base Python tools/package_retina_conda.py WHEEL OUTPUT_DIRECTORY
"""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import zipfile
from conda_package_handling.api import create

wheel, destination = map(Path,sys.argv[1:])
expected = '117c528129963ee6b3c9b3b36991ef11e9f76586868d46132ff7b47e0cbd761c'
assert hashlib.sha256(wheel.read_bytes()).hexdigest() == expected, 'Official wheel checksum mismatch'
destination.mkdir(parents=True,exist_ok=True)
with tempfile.TemporaryDirectory() as directory:
    root=Path(directory)
    with zipfile.ZipFile(wheel) as archive:
        for entry in archive.infolist():
            path=Path(entry.filename)
            assert not path.is_absolute() and '..' not in path.parts
            if entry.is_dir():continue
            target=root/'site-packages'/path
            target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes(archive.read(entry))
    files=sorted(str(p.relative_to(root)) for p in root.rglob('*') if p.is_file())
    info=root/'info';info.mkdir()
    (info/'index.json').write_text(json.dumps({'name':'retina-face','version':'0.0.19','build':'local_pytorch_0','build_number':0,'subdir':'noarch','noarch':'python','license':'MIT','depends':['python >=3.9','numpy >=1.14','opencv >=4.5.5','gdown >=3.10.1','requests >=2.27.1','pytorch >=1.13']}))
    (info/'link.json').write_text(json.dumps({'package_metadata_version':1,'noarch':{'type':'python','entry_points':[]}}))
    (info/'files').write_text('\n'.join(files)+'\n')
    (info/'paths.json').write_text(json.dumps({'paths_version':1,'paths':[{'_path':f,'path_type':'hardlink','sha256':hashlib.sha256((root/f).read_bytes()).hexdigest(),'size_in_bytes':(root/f).stat().st_size} for f in files]}))
    (info/'about.json').write_text(json.dumps({'home':'https://github.com/serengil/retinaface','license':'MIT','summary':'Unmodified upstream RetinaFace 0.0.19; conda PyTorch backend variant','source_wheel_sha256':expected}))
    all_files=sorted(str(p.relative_to(root)) for p in root.rglob('*') if p.is_file())
    print(create(str(root),all_files,'retina-face-0.0.19-local_pytorch_0.conda',out_folder=str(destination.resolve())))
