"""Replay one retained local capture through the real reconstruction protocol.

The report contains hashes and states only; footage stays in the private jobs
directory and is removed by the worker after success or failure.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path
from urllib.request import Request, urlopen


ROOT = 'http://127.0.0.1:8787/v1/reconstruction'
CHUNK = 1048576


def access_token() -> str:
    env = Path(__file__).with_name('.env')
    if not env.is_file():
        return ''
    for line in env.read_text(encoding='utf-8').splitlines():
        if line.startswith('SELF_BACKEND_TOKEN='):
            return line.partition('=')[2].strip().strip('"\'')
    return ''


def request(path: str, token: str, method: str = 'GET', data: bytes | None = None,
            headers: dict[str, str] | None = None) -> bytes:
    values = dict(headers or {})
    if token:
        values['Authorization'] = 'Bearer ' + token
    req = Request(ROOT + path, data=data, method=method, headers=values)
    with urlopen(req, timeout=70) as response:
        return response.read()


def replay(source: Path, evidence: Path, timeout_seconds: int) -> dict:
    token = access_token()
    digest = hashlib.sha256()
    size = 0
    with source.open('rb') as stream:
        for piece in iter(lambda: stream.read(CHUNK), b''):
            digest.update(piece)
            size += len(piece)
    capture_sha = digest.hexdigest()
    created = json.loads(request('/jobs', token, 'POST', json.dumps({
        'totalBytes': size, 'sha256': capture_sha, 'format': 'mp4'
    }).encode('utf-8'), {'Content-Type': 'application/json'}))
    job_id = created['jobId']
    report = {'jobId': job_id, 'captureSha256': capture_sha,
              'captureBytes': size, 'protocolChunkBytes': created['chunkBytes']}
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(report, indent=2), encoding='utf-8')
    with source.open('rb') as stream:
        for index, piece in enumerate(iter(lambda: stream.read(CHUNK), b'')):
            receipt = json.loads(request(f'/jobs/{job_id}/chunks/{index}', token,
                'PUT', piece, {'Content-Type': 'application/octet-stream',
                               'X-Content-SHA256': hashlib.sha256(piece).hexdigest()}))
            if receipt['index'] != index or receipt['sha256'] != hashlib.sha256(piece).hexdigest():
                raise RuntimeError('upload_receipt_mismatch')
    sealed = json.loads(request(f'/jobs/{job_id}/seal', token, 'POST', b'{}',
                                {'Content-Type': 'application/json'}))
    if sealed['state'] != 'queued' or sealed['sha256'] != capture_sha:
        raise RuntimeError('seal_mismatch')
    deadline = time.monotonic() + timeout_seconds
    previous = None
    while time.monotonic() < deadline:
        status = json.loads(request(f'/jobs/{job_id}', token))
        current = (status['state'], status['progress'])
        if current != previous:
            print(f'{job_id} {current[0]} {current[1]}%', flush=True)
            previous = current
        if status['state'] in ('gaussian_ready', 'failed', 'cancelled'):
            report.update(state=status['state'], message=status['message'],
                          assets=status['assets'])
            break
        time.sleep(5)
    else:
        report['state'] = 'timed_out_waiting_for_worker'
    if report['state'] == 'gaussian_ready':
        for kind in ('view', 'gaussian'):
            manifest = report['assets'][kind]
            actual = hashlib.sha256()
            received = 0
            count = (manifest['bytes'] + CHUNK - 1) // CHUNK
            for index in range(count):
                path = f'/jobs/{job_id}/assets/{kind}'
                if kind == 'gaussian':
                    path += f'/chunks/{index}'
                piece = request(path, token)
                if kind == 'gaussian' and index == 0 and not piece.startswith(b'ply\n'):
                    raise RuntimeError('download_not_ply')
                actual.update(piece)
                received += len(piece)
            if received != manifest['bytes'] or actual.hexdigest() != manifest['sha256']:
                raise RuntimeError(f'{kind}_download_digest_mismatch')
            report[kind + 'DownloadVerified'] = True
    evidence.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('source', type=Path)
    parser.add_argument('evidence', type=Path)
    parser.add_argument('--timeout-seconds', type=int, default=1200)
    args = parser.parse_args()
    result = replay(args.source, args.evidence, args.timeout_seconds)
    print(json.dumps({'jobId': result['jobId'], 'state': result['state'],
                      'gaussianVerified': result.get('gaussianDownloadVerified', False)},
                     ensure_ascii=False), flush=True)
    raise SystemExit(0 if result['state'] == 'gaussian_ready' else 1)
