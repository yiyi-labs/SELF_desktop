"""Fail without printing secret values if configured credentials enter delivery."""
import argparse,json,subprocess,zipfile
from pathlib import Path
from dotenv import dotenv_values

root=Path(__file__).resolve().parents[1]
args=argparse.ArgumentParser();args.add_argument('--archives',action='store_true');args=args.parse_args()
env=dotenv_values(root/'backend/.env') if (root/'backend/.env').exists() else {}
secrets=[v.encode() for k,v in env.items() if k in ('DEEPSEEK_API_KEY','SELF_BACKEND_TOKEN') and v and len(v)>=8]
matches=[];count=0
def inspect(name,data):
    global count
    count+=1
    if any(s in data for s in secrets):matches.append(name)

paths=subprocess.check_output(['git','ls-files','--cached','--others','--exclude-standard','-z'],cwd=root).decode().split('\0')
for name in filter(None,paths):
    p=root/name
    if p.is_file():inspect(name,p.read_bytes())
if args.archives:
    for name in ('SELF-debug-unsigned.hap','SELF-source-and-evidence.zip'):
        with zipfile.ZipFile(root/'artifacts'/name) as archive:
            for item in archive.infolist():
                if item.is_dir():continue
                leaf=Path(item.filename).name
                if leaf.startswith('.env') and leaf!='.env.example':matches.append(name+':'+item.filename)
                inspect(name+':'+item.filename,archive.read(item))
result={'configuredCredentialsChecked':len(secrets),'filesChecked':count,'pass':not matches,'matchingPaths':matches}
print(json.dumps(result,indent=2))
if matches:raise SystemExit(1)
