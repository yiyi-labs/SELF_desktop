"""Native full-canvas projection. ROI is a loss/output domain, never a viewport."""
import torch
from reconstruction_portrait_pipeline import draw


def canvas(frame):
    if frame.get('nativeScale') != 1:
        raise ValueError('native_full_canvas_required')
    if 'fullSize' not in frame or 'rectangle' not in frame:
        raise ValueError('missing_recorded_full_canvas_metadata')
    w,h=map(int,frame['fullSize']);x0,y0,x1,y1=map(int,frame['rectangle'])
    if not (0<=x0<x1<=w and 0<=y0<y1<=h):raise ValueError('invalid_roi')
    full_K=frame.get('fullK')
    if full_K is None:
        # Explicit native crop rectangle + original canvas uniquely restores K.
        # No inference from a face bounding box or image size is permitted.
        full_K=frame['K'].clone();full_K[0,2]+=x0;full_K[1,2]+=y0
    expected=full_K.clone();expected[0,2]-=x0;expected[1,2]-=y0
    if not torch.allclose(expected,frame['K'],rtol=0,atol=1e-5):raise ValueError('crop_K_contract_mismatch')
    if frame['rgb'].shape[:2] != (y1-y0,x1-x0):raise ValueError('crop_tensor_contract_mismatch')
    return w,h,(x0,y0,x1,y1),full_K


def slice_render(full, rectangle):
    x0,y0,x1,y1=rectangle
    result={key:(value[y0:y1,x0:x1] if key!='info' else value) for key,value in full.items()}
    # info retains original width, height, means2d, conics and radii. No ROI
    # coordinate shift: strategy statistics must describe the original canvas.
    return result


def draw_frame(state,C,frame,*,unit_scale=1.,antialiased=False,absgrad=False,return_full=False):
    w,h,rect,K=canvas(frame)
    full=draw(state,C,K,w,h,unit_scale=unit_scale,antialiased=antialiased,absgrad=absgrad)
    full['info']['width']=w;full['info']['height']=h
    roi=slice_render(full,rect)
    return (roi,full) if return_full else roi


class ViewGradientStatistics:
    """Consume each view AFTER its backward, before any topology mutation.

    Independent per-view snapshots avoid overwriting the first accumulation.
    This records statistics; it does not turn on a density strategy by itself.
    """
    def __init__(self):self.views=[]
    def consume(self,info):
        g=getattr(info['means2d'],'absgrad',None)
        if g is None:g=info['means2d'].grad
        if g is None:raise ValueError('backward_required_before_statistics')
        self.views.append({'width':int(info['width']),'height':int(info['height']),
            'ids':info['gaussian_ids'].detach().clone(),'gradient':g.detach().clone(),
            'radii':info['radii'].detach().clone()})
    def summary(self):return [{'width':v['width'],'height':v['height'],'count':len(v['ids']),
        'gradientL1':float(v['gradient'].abs().sum())} for v in self.views]
