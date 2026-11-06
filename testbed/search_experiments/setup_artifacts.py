"""Import checksummed external inputs; prepare pinned app source. No API or DB calls."""
import argparse,gzip,hashlib,io,json,subprocess,tarfile
from pathlib import Path
ROOT=Path(__file__).resolve().parent
REPO=ROOT.parents[1]
def sha(raw):return hashlib.sha256(raw).hexdigest()
def read(p):return json.loads(p.read_text())
def save(p,x):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n')
def safe_path(name):
 p=(ROOT/name).resolve()
 if not p.is_relative_to(ROOT) or Path(name).is_absolute() or '..' in Path(name).parts:raise ValueError('Unsafe member path')
 return p
def import_bundle(kind,path):
 manifest=read(ROOT/'artifacts.json')[kind]
 if sha(path.read_bytes())!=manifest['sha256']:raise ValueError('Archive checksum mismatch')
 with tarfile.open(path,'r:gz') as archive:
  members=archive.getmembers()
  if len(members)!=len(manifest['files']) or {m.name for m in members}!=set(manifest['files']):raise ValueError('Unexpected archive members')
  # Validate everything before writing anything; never overwrite a changed result.
  for m in members:
   if not m.isfile():raise ValueError('Only regular files are supported')
   dest=safe_path(m.name);data=archive.extractfile(m).read()
   if sha(data)!=manifest['files'][m.name]:raise ValueError('Member checksum mismatch')
   if dest.exists() and sha(dest.read_bytes())!=sha(data):raise ValueError(f'Refusing to replace modified file: {m.name}')
  for m in members:
   dest=safe_path(m.name)
   if not dest.exists():dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(archive.extractfile(m).read())
 print(f'Imported {kind}: {len(members)} files')
def prepare_family():
 f=ROOT/'family_history';source=read(f/'provenance/source_lock.json');inputs={};datasets={}
 for old,h in source['inputs'].items():
  if '/memoryqa_scaling/' in old:
   path=old.removeprefix('talkdock-memoryqa-pr/');assert sha((REPO/path).read_bytes())==h,path;datasets[path]=h
  else:
   path='.inputs/'+old.split('/output/',1)[1];assert sha((f/path).read_bytes())==h,path;inputs[path]=h
 inputs['cases.json']=source['cases_hash']
 # Also lock SQL/graph snapshots, rather than only the seed metadata.
 for path,h in read(ROOT/'artifacts.json')['family_history']['files'].items():inputs[path.removeprefix('family_history/')]=h
 raw=subprocess.check_output(['git','archive',source['app_commit'],'backend'],cwd=REPO)
 with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
  for m in archive.getmembers():
   if not m.isfile():continue
   p=safe_path('family_history/.runtime/'+m.name)
   if p.exists() and p.read_bytes()!=archive.extractfile(m).read():raise ValueError('Pinned app file changed')
   p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(archive.extractfile(m).read())
 for name,h in source['app_files'].items():assert sha((f/name).read_bytes())==h,name
 save(f/'runtime_lock.json',{'inputs':inputs,'app_files':source['app_files'],'dataset_files':datasets})
 # Adapt only the snapshot wrapper to the repository's existing safe restore helper.
 groups={}
 for size in [100,200,300]:
  doc=read_gzip(f/f'.inputs/history_{size}/graph.json.gz');bodyhash=sha(json.dumps(doc,ensure_ascii=False,sort_keys=True).encode())
  expected=read(f/f'.inputs/history_{size}/graph_seed.json')['fingerprint'];assert bodyhash==expected
  doc.update(group_id=f'family_{832000+size}',content_sha256=bodyhash,recorded_fingerprint=expected,history_size=size,schema_version=1)
  name=f'snapshots/history_{size}/graph.json.gz';target=f/'.inputs/restore'/name;target.parent.mkdir(parents=True,exist_ok=True)
  target.write_bytes(gzip.compress(json.dumps(doc,ensure_ascii=False).encode(),mtime=0))
  groups[str(size)]={'path':name,'sha256':sha(target.read_bytes()),'content_sha256':bodyhash,'nodes':len(doc['nodes']),'edges':len(doc['edges']),'group_id':doc['group_id']}
 save(f/'.inputs/restore/snapshots/graph_manifest.json',{'groups':groups})
 print('Pinned app and graph restore manifest ready; no service was contacted')
def read_gzip(p):return json.loads(gzip.decompress(p.read_bytes()))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('kind',choices=['family_history','post_qa']);p.add_argument('archive',type=Path);a=p.parse_args()
 import_bundle(a.kind,a.archive)
 if a.kind=='family_history':prepare_family()
