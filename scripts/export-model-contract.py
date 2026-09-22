import sys,json
from pathlib import Path
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/'backend'))
from contracts import Plan,Snapshot,PRESETS,LEVELS
folder=root/'shared/contracts';folder.mkdir(parents=True,exist_ok=True)
for name,content in {'candidate-plan-v1.schema.json':Plan.model_json_schema(),'snapshot-v1.schema.json':Snapshot.model_json_schema(),'effect-registry-v1.json':{'schemaVersion':1,'presets':PRESETS,'levels':LEVELS,'calibratedProductProfiles':[]}}.items():
    (folder/name).write_text(json.dumps(content,ensure_ascii=False,indent=2),encoding='utf-8')
print('Exported schemas directly from the production backend registry.')
