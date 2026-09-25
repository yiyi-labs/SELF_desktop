"""Import user-supplied, audited research evidence without upgrading its status.

This is a reproducible file copy, not a live catalog crawl or product calibration.
"""
from pathlib import Path
import hashlib
import json
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PREFIX = 'SELF_OLAY_CN_AUDITED_20260925_v2/'
FILES = (
    'data/coverage.json', 'data/products_cn.json',
    'data/source_rechecks.json', 'data/product_dossiers_cn.json',
    'data/calibration_profiles.json', 'data/approved_release_manifest.json',
)

def main(source: Path) -> None:
    with zipfile.ZipFile(source) as archive:
        payload = {name: archive.read(PREFIX + name) for name in FILES}
    coverage = json.loads(payload['data/coverage.json'])
    products = json.loads(payload['data/products_cn.json'])
    calibrations = json.loads(payload['data/calibration_profiles.json'])
    approved = json.loads(payload['data/approved_release_manifest.json'])
    if (coverage['dataset_version'] != '2026-09-25.audit-v2' or
        len(products) != 74 or calibrations or approved or
        coverage['global_or_mainland_complete_catalog'] or
        coverage['real_product_render_parameters_available']):
        raise SystemExit('Audit status changed: review before importing')
    destination = ROOT / 'shared/products/audit-v2'
    destination.mkdir(parents=True, exist_ok=True)
    for name, raw in payload.items():
        (destination / Path(name).name).write_bytes(raw)
    provenance = {
        'sourceArchiveSha256': hashlib.sha256(source.read_bytes()).hexdigest(),
        'datasetVersion': coverage['dataset_version'],
        'importedFiles': {Path(name).name: hashlib.sha256(raw).hexdigest() for name,raw in payload.items()},
        'semanticStatus': 'research_evidence_only_not_a_complete_current_product_or_calibration_catalog',
    }
    (destination / 'provenance.json').write_text(json.dumps(provenance,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('Imported 74 research records, 0 calibration profiles, 0 approved release entries.')

if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit('Usage: import-olay-audit.py AUDITED_V2.zip')
    main(Path(sys.argv[1]))
