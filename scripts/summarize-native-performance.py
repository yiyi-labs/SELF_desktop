from pathlib import Path
import json,re
root=Path(__file__).resolve().parents[1]/'docs/evidence/native-es3'
result={'metricLimits':'CPU submit+eglSwapBuffers and CPU render-start intervals, not GPU completion or actual display presentation. Emulator only; mixed UI workload. Memory sampling may start after warm-up.'}
for label,log,mem in [('before','stress-before-runtime.log','stress-memory-before.json'),('after','stress-runtime.log','stress-memory.json')]:
    path=root/log
    if not path.exists():continue
    text=path.read_text(encoding='utf-8-sig')
    stats=[json.loads(line.split('SELF_NATIVE_STATS ',1)[1]) for line in text.splitlines() if 'SELF_NATIVE_STATS ' in line]
    completed=[json.loads(line.split('SELF_STRESS_FINISHED ',1)[1]) for line in text.splitlines() if 'SELF_STRESS_FINISHED ' in line]
    records=json.loads((root/mem).read_text(encoding='utf-8-sig')) if (root/mem).exists() else []
    rss=[];hwm=[]
    for record in records:
        for value in record['memory']:
            if value.startswith('VmRSS:'):rss.append(int(re.search(r'\d+',value)[0]))
            if value.startswith('VmHWM:'):hwm.append(int(re.search(r'\d+',value)[0]))
    result[label]={'lastStats':stats[-1] if stats else None,'completed':completed[-1] if completed else None,
                   'memorySamples':len(records),'firstRssKiB':rss[0] if rss else None,'lastRssKiB':rss[-1] if rss else None,'peakRssKiB':max(rss) if rss else None,'processHighWaterKiB':max(hwm) if hwm else None}
(root/'performance-summary.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
print(json.dumps(result,indent=2))
