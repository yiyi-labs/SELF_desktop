"""Continuous decoder contract used by isolated point trackers."""
import subprocess,json
import numpy as np,cv2
from reconstruction_temporal_observations import source_indices

def decode_window(prep,source,identity,names,images):
    values=json.loads(subprocess.check_output(['ffprobe','-v','error','-select_streams','v:0','-show_frames','-show_entries','frame=best_effort_timestamp_time','-of','json',str(source)],text=True))
    times=np.array([float(r['best_effort_timestamp_time']) for r in values['frames']]);idx=source_indices(times,[identity[n] for n in names])
    h,w=images[names[0]].shape[:2];audit=json.loads((prep/'pose-and-scale-audit.json').read_text());K=np.asarray(audit['K']);dist=np.asarray(audit['sourceRadialDistortion']);mx,my=cv2.initUndistortRectifyMap(K,dist,np.eye(3),K,(w,h),cv2.CV_32FC1)
    needed=set(int(i) for i in idx);frames={};cap=cv2.VideoCapture(str(source));i=0
    while i<=max(needed):
        ok,frame=cap.read()
        if not ok:raise ValueError('source_decode_incomplete')
        if i in needed:
            frame=cv2.cvtColor(frame,cv2.COLOR_BGR2RGB)
            if frame.shape[:2]!=(h,w):raise ValueError('native_video_orientation_mismatch')
            frames[i]=cv2.remap(frame,mx,my,cv2.INTER_LINEAR)
        i+=1
    cap.release();positions={}
    for n in names:
        si=identity[n]['sourceIndexZeroBased'];positions[n]=int(np.flatnonzero(idx==si)[0]);difference=float(abs(frames[si].astype(float)-images[n]).mean()/255)
        if difference>.005:raise ValueError('source_anchor_disagreement:'+n)
        frames[si]=images[n]
    return [frames[int(i)] for i in idx],positions,idx,times[idx]
