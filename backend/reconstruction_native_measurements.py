"""A network proposal is localized again in native RGB with independent checks.
Final precision gates are native; coarse network pixels are not measurements.
"""
import numpy as np,cv2
from reconstruction_temporal_observations import bounded_native_affine,affine_center_delta

def locate_patch(template,image,proposal,radius=20):
    size=template.shape[0];half=size//2;h,w=image.shape[:2];p=np.asarray(proposal,float);x,y=np.rint(p).astype(int)
    if not(half+radius<x<w-half-radius-1 and half+radius<y<h-half-radius-1):raise ValueError('native_search_boundary')
    if template.std()<.010:raise ValueError('native_template_low_texture')
    search=image[y-half-radius:y+half+radius+1,x-half-radius:x+half+radius+1].astype(np.float32)/255
    scores=cv2.matchTemplate(search,template,cv2.TM_CCOEFF_NORMED);_,peak,_,loc=cv2.minMaxLoc(scores);lx,ly=loc
    rival=scores.copy();rival[max(0,ly-3):ly+4,max(0,lx-3):lx+4]=-1
    if peak<.78 or peak-float(rival.max())<.025:raise ValueError('native_ambiguous_search')
    center=np.array([x-radius+lx,y-radius+ly],np.float32);target=cv2.getRectSubPix(image,(size,size),tuple(center)).astype(np.float32)/255
    warp,corr,cycle=bounded_native_affine(template,target)
    return center+affine_center_delta(warp,template.shape),float(corr),float(peak-rival.max()),cycle

def native_measurement(source_image,target_image,source_uv,proposal):
    template=cv2.getRectSubPix(source_image,(25,25),tuple(np.asarray(source_uv,np.float32))).astype(np.float32)/255
    uv,corr,margin,cycle=locate_patch(template,target_image,proposal)
    reverse_template=cv2.getRectSubPix(target_image,(25,25),tuple(uv.astype(np.float32))).astype(np.float32)/255
    back,rc,rm,cycle2=locate_patch(reverse_template,source_image,source_uv,radius=5)
    fb=float(np.linalg.norm(back-source_uv))
    if fb>1:raise ValueError('native_forward_reverse_precision')
    return uv,dict(fb=fb,correlation=min(corr,rc),peakMargin=min(margin,rm),affineCycle=max(cycle,cycle2))
