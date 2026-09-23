"""Original synthetic GS fixture, test HAP only. Not a scan or personal portrait."""
from pathlib import Path
from math import log
root = Path(__file__).resolve().parent.parent
target = root / 'entry/src/ohosTest/resources/rawfile/gs-probe/occlusion.ply'
names = ['x','y','z','nx','ny','nz'] + [f'f_dc_{i}' for i in range(3)] + [f'f_rest_{i}' for i in range(45)] + ['opacity'] + [f'scale_{i}' for i in range(3)] + [f'rot_{i}' for i in range(4)]
rows = []
for z, color in [(0., (.2,.8,.2)), (-.4, (.2,.2,.8))]:
    for y in range(-4,5):
        for x in range(-4,5):
            rows.append([x*.05, y*.05,z,0,0,0] + [(c-.5)/.28209479177387814 for c in color] + [0]*45 + [log(.999/.001)] + [log(.06),log(.06),log(.002)] + [1,0,0,0])
header = ['ply','format ascii 1.0','comment SELF original synthetic occlusion fixture; not reconstructed anatomy',f'element vertex {len(rows)}'] + ['property float '+n for n in names] + ['end_header']
target.parent.mkdir(parents=True,exist_ok=True)
target.write_text('\n'.join(header + [' '.join(format(v,'.9g') for v in row) for row in rows])+'\n', encoding='ascii')
print(f'Wrote {len(rows)} synthetic Gaussians to test resources')
