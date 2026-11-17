#!/usr/bin/python3
"""Root-owned Certbot hook; only this project's certificate and Nginx are handled."""
import hashlib
import json
import os
from pathlib import Path
import ssl
import stat
import subprocess
import sys
import tempfile

BASE = Path('/var/lib/sinegor-lab-prod')
LINEAGE = Path('/etc/letsencrypt/live/sinegor-lab-prod')
PROXY = 'sinegor-lab-prod-proxy-1'
PREFIX = '/etc/nginx/sinegor/'
DOMAINS = {'sinegor-lab.website', 'cms.sinegor-lab.website'}


def require(value):
    if not value:
        raise RuntimeError('tls_deploy_guard')


def run(args):
    p = subprocess.run(args, stdin=subprocess.DEVNULL, capture_output=True, timeout=45)
    require(p.returncode == 0)
    return p.stdout


def write(path, data, mode, uid=0, gid=0):
    require(path.parent.is_dir() and not path.parent.is_symlink())
    if path.exists() or path.is_symlink():
        require(stat.S_ISREG(path.lstat().st_mode))
    fd, name = tempfile.mkstemp(prefix='.tls-', dir=path.parent)
    try:
        os.fchmod(fd, mode); os.fchown(fd, uid, gid)
        with os.fdopen(fd, 'wb') as out:
            out.write(data); out.flush(); os.fsync(out.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def main():
    require(os.getuid() == 0)
    if os.environ.get('RENEWED_LINEAGE') != str(LINEAGE):
        return
    guard = json.loads((BASE / 'deploy-guard.json').read_text())
    item = json.loads(run(['/usr/bin/docker', 'inspect', PROXY]))[0]
    require(item['Config']['Labels'].get('com.docker.compose.project') == 'sinegor-lab-prod')
    require(item['Image'] == guard['nginxImageId'] and item['State']['Status'] == 'running')
    require(item['Config']['User'] in ['101', '101:101'] and item['HostConfig']['ReadonlyRootfs'])
    mode = None
    for candidate in ['bootstrap', 'https']:
        if item['Config']['Cmd'] == ['nginx', '-c', PREFIX + 'nginx.' + candidate + '.conf', '-g', 'daemon off;']:
            mode = candidate
    require(mode is not None)
    certificate = LINEAGE / 'fullchain.pem'; key = LINEAGE / 'privkey.pem'
    decoded = ssl._ssl._test_decode_cert(str(certificate))
    require({value for kind, value in decoded['subjectAltName'] if kind == 'DNS'} == DOMAINS)
    run(['/usr/bin/openssl', 'x509', '-in', str(certificate), '-checkend', '86400', '-noout'])
    run(['/usr/bin/openssl', 'verify', '-CApath', '/etc/ssl/certs', '-untrusted', str(LINEAGE / 'chain.pem'), str(LINEAGE / 'cert.pem')])
    cert_pub = run(['/usr/bin/openssl', 'x509', '-in', str(certificate), '-pubkey', '-noout'])
    key_pub = run(['/usr/bin/openssl', 'pkey', '-in', str(key), '-pubout'])
    require(cert_pub == key_pub)
    tls = BASE / 'tls'
    old = {name: (tls / name).read_bytes() if (tls / name).exists() else None for name in ['cert.pem', 'key.pem']}
    try:
        write(tls / 'cert.pem', certificate.read_bytes(), 0o644, 0, 101)
        write(tls / 'key.pem', key.read_bytes(), 0o640, 0, 101)
        if mode == 'https':
            run(['/usr/bin/docker', 'exec', '--user', '101:101', PROXY, 'nginx', '-t', '-c', PREFIX + 'nginx.https.conf'])
            run(['/usr/bin/docker', 'exec', '--user', '101:101', PROXY, 'nginx', '-s', 'reload', '-c', PREFIX + 'nginx.https.conf'])
    except Exception:
        restored = True
        for name, content in old.items():
            try:
                if content is not None:
                    write(tls / name, content, 0o640 if name == 'key.pem' else 0o644, 0, 101)
                elif (tls / name).exists():
                    (tls / name).unlink()
            except Exception:
                restored = False
        require(restored)
        raise
    state = BASE / 'tls-deploy-state.json'
    generation = json.loads(state.read_text())['generation'] + 1 if state.exists() else 1
    write(state, json.dumps({'generation': generation, 'mode': mode,
                            'certificateSha256': hashlib.sha256(certificate.read_bytes()).hexdigest(),
                            'notAfter': decoded['notAfter']}, sort_keys=True).encode(), 0o600)
    print('SINEGOR_TLS_DEPLOY_OK', mode, generation)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print('SINEGOR_TLS_DEPLOY_FAILED', type(error).__name__)
        sys.exit(1)
