"""Compatibility entry for the one callable portrait pipeline.

No monkey patches, separate renderer, or independent training algorithm.
The transport's existing asset identifier stays valid; Git hashes identify
the implementation that actually ran.
"""
from pathlib import Path
import argparse
import reconstruction_portrait_pipeline as pipeline

VERSION=pipeline.ENGINE_VERSION
CAPABILITIES=["native-full-canvas-before-roi", "explicit-covariance-no-factorization",
              "head-local-sh1-world-transport", "common-scene-alpha-composition",
              "same-capture-only-preparation", "git-source-identity"]
native_frame=pipeline.make_frame
native_draw=pipeline.full_frame_draw
NativeScene=pipeline.SceneAssembly


def run(args):
    if args.joint_steps != 0:
        raise ValueError("rejected_T2_cannot_enable_new_face_joint_updates")
    pipeline.run(args)


if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("prepared",type=Path);p.add_argument("output",type=Path)
    p.add_argument("--soft",action="store_true");p.add_argument("--antialiased",action="store_true")
    p.add_argument("--local-steps",type=int,default=900);p.add_argument("--room-steps",type=int,default=300)
    p.add_argument("--joint-steps",type=int,default=0);p.add_argument("--resume-state",type=Path)
    p.add_argument("--surface-refine",action="store_true")
    p.add_argument("--dense-surfaces",action="store_true");p.add_argument("--dense-manifest",type=Path)
    p.add_argument('--portrait-state',type=Path);p.add_argument('--portrait-manifest',type=Path)
    p.add_argument('--shared-room-surface',action='store_true');p.add_argument('--hair-steps',type=int,default=0)
    p.add_argument('--observed-face-domain',action='store_true')
    run(p.parse_args())
