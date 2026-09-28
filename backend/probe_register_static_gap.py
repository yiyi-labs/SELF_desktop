"""Try real 2D-3D localization for static SfM gaps; never interpolate poses."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pycolmap

from probe_static_alignment import best_model


def run(job: Path) -> dict:
    root = job / "static_sfm_probe_stride1"
    model = best_model(root / "sparse")
    before = model.num_reg_images()
    with pycolmap.Database.open(root / "colmap.db") as database:
        cache = pycolmap.DatabaseCache.create(database, pycolmap.DatabaseCacheOptions())
        mapper = pycolmap.IncrementalMapper(cache)
        mapper.begin_reconstruction(model)
        options = pycolmap.IncrementalMapperOptions()
        missing = [image for image in database.read_all_images()
                   if image.name not in {item.name for item in model.images.values() if item.has_pose}]
        succeeded = []
        # Retry only after an actual 2D-3D localization succeeds. No synthetic
        # camera poses or interpolation enter this model.
        for _ in range(3):
            prior = len(succeeded)
            for image in list(missing):
                if mapper.register_next_image(options, image.image_id):
                    succeeded.append(image.name)
                    missing.remove(image)
            if len(succeeded) == prior:
                break
        mapper.end_reconstruction(False)
    report = {"registeredBefore": before, "registeredAfter": model.num_reg_images(),
              "newlyLocalized": len(succeeded), "stillMissing": len(missing),
              "method": "masked_static_2d3d_localization_only"}
    if succeeded:
        output = root / "localized_static"
        output.mkdir(exist_ok=True)
        model.write(output)
    (root / "localization_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report), flush=True)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("job", type=Path)
    run(parser.parse_args().job)
