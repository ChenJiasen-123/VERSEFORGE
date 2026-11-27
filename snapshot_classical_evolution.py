"""Supplementary full dependency snapshot; no environment variables or credentials."""
import argparse,hashlib,json,sys,platform
from pathlib import Path
ROOT=Path(__file__).resolve().parent

def paths():
 out=list((ROOT/'poetry_agent').rglob('*.py'))+list((ROOT/'poetry_agent/data').glob('*.json'))
 out+=list((ROOT/'experiments/classical_evolution').glob('*.py'))+list((ROOT/'experiments/classical_evolution').glob('*.json'))
 out+=list((ROOT/'experiments/evolution').glob('*.py'))
 out += [ROOT/'experiments/reverse_prompt_engineering/metrics.py',ROOT/'experiments/reverse_prompt_engineering/optimizer.py',ROOT/'third_party/opencc/STCharacters.txt']
 return sorted(set(out))
def collect():return {str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths()}
def main():
 p=argparse.ArgumentParser();p.add_argument('command',choices=['create','verify']);p.add_argument('snapshot',type=Path);a=p.parse_args()
 if a.command=='create':
  if a.snapshot.exists():raise ValueError('snapshot exists')
  data={'files':collect(),'python_version':platform.python_version(),'system':platform.system(),
        'scope':'Generation/selection/baseline code, classical datasets, historical lexicons and glyph source. No environment variables.'}
  a.snapshot.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8');print('snapshot_created',len(data['files']))
 else:
  old=json.loads(a.snapshot.read_text(encoding='utf-8'));now=collect();changed=[name for name in set(old['files'])|set(now) if old['files'].get(name)!=now.get(name)]
  print(json.dumps({'unchanged':not changed,'changed_files':changed},ensure_ascii=False))
  if changed:sys.exit(2)
if __name__=='__main__':main()
