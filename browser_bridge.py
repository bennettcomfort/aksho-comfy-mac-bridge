#!/usr/bin/env python3
"""Accept both HTTP and HTTPS on the port Atelier already uses.

https://akshoai.com sends Content-Security-Policy: upgrade-insecure-requests.
Chrome and Firefox leave http://127.0.0.1 alone. Safari rewrites it to
https://127.0.0.1 and the request dies, because ComfyUI only speaks HTTP.

ComfyUI keeps listening on 127.0.0.1:18188. nginx listens on 127.0.0.1:8188,
the address Atelier uses. Plain connections are forwarded as-is. TLS
connections are decrypted with a local certificate and then forwarded.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path
from typing import NoReturn

PUBLIC_PORT = 8188
INTERNAL_PORT = 18188
TLS_PORT = 18443
CA_NAME = "Aksho Comfy Local CA"


def info(message: str) -> None:
    print(f"[AKSHO COMFY] {message}", flush=True)


def die(message: str) -> NoReturn:
    info(f"ERROR: {message}")
    raise SystemExit(1)


def openssl() -> str:
    brew = Path("/opt/homebrew/bin/openssl")
    if brew.is_file():
        return str(brew)
    found = shutil.which("openssl")
    if found:
        return found
    die("openssl is not installed, so Safari cannot be given a local certificate.")


def nginx_bin() -> str:
    brew = Path("/opt/homebrew/bin/nginx")
    if brew.is_file():
        return str(brew)
    found = shutil.which("nginx")
    if found:
        return found
    die("nginx is not installed. Safari needs it to accept HTTPS on port 8188. Install it with: brew install nginx")


def bridge_dir(root: Path) -> Path:
    return root / "bridge"


def run(command: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=False, text=True, capture_output=True, **kwargs)


def ensure_certs(root: Path) -> tuple[Path, Path]:
    folder = root / "certs"
    folder.mkdir(parents=True, exist_ok=True)
    ca_key = folder / "ca.key"
    ca_cert = folder / "ca.pem"
    server_key = folder / "server.key"
    server_cert = folder / "server.pem"
    fullchain = folder / "fullchain.pem"
    if ca_cert.is_file() and server_cert.is_file() and fullchain.is_file() and server_key.is_file():
        return fullchain, server_key

    tool = openssl()
    ca_config = folder / "ca.cnf"
    server_config = folder / "server.cnf"
    ca_config.write_text(
        "[req]\n"
        "distinguished_name = dn\n"
        "x509_extensions = ext\n"
        "prompt = no\n"
        "[dn]\n"
        f"CN = {CA_NAME}\n"
        "[ext]\n"
        "basicConstraints = critical,CA:TRUE\n"
        "keyUsage = critical,keyCertSign,cRLSign\n"
        "subjectKeyIdentifier = hash\n",
        encoding="utf-8",
    )
    server_config.write_text(
        "[req]\n"
        "distinguished_name = dn\n"
        "req_extensions = ext\n"
        "prompt = no\n"
        "[dn]\n"
        "CN = 127.0.0.1\n"
        "[ext]\n"
        "basicConstraints = CA:FALSE\n"
        "keyUsage = critical,digitalSignature,keyEncipherment\n"
        "extendedKeyUsage = serverAuth\n"
        "subjectAltName = IP:127.0.0.1,DNS:localhost\n",
        encoding="utf-8",
    )
    steps = [
        [tool, "req", "-x509", "-newkey", "rsa:2048", "-sha256", "-days", "825", "-nodes",
         "-keyout", str(ca_key), "-out", str(ca_cert), "-config", str(ca_config)],
        [tool, "req", "-newkey", "rsa:2048", "-sha256", "-nodes",
         "-keyout", str(server_key), "-out", str(folder / "server.csr"), "-config", str(server_config)],
        [tool, "x509", "-req", "-in", str(folder / "server.csr"), "-CA", str(ca_cert), "-CAkey", str(ca_key),
         "-CAcreateserial", "-out", str(server_cert), "-days", "825", "-sha256",
         "-copy_extensions", "copy"],
    ]
    for command in steps:
        result = run(command)
        if result.returncode != 0:
            die(f"Could not create the local certificate.\n{result.stderr.strip()}")
    fullchain.write_text(server_cert.read_text(encoding="utf-8") + ca_cert.read_text(encoding="utf-8"), encoding="utf-8")
    for path in (ca_key, server_key):
        path.chmod(0o600)
    info("Created a local certificate for 127.0.0.1.")
    return fullchain, server_key


def trust_ca(root: Path) -> None:
    ca_cert = root / "certs" / "ca.pem"
    check = run(["security", "verify-cert", "-c", str(root / "certs" / "server.pem"), "-p", "ssl"])
    if check.returncode == 0:
        return
    keychain = Path.home() / "Library" / "Keychains" / "login.keychain-db"
    info("macOS needs to trust this certificate once so Safari can open the local connection.")
    info("If a keychain window appears, approve it. It is only for 127.0.0.1.")
    result = run([
        "security", "add-trusted-cert", "-r", "trustRoot",
        "-k", str(keychain), str(ca_cert),
    ])
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        die(
            "Safari still will not trust https://127.0.0.1. "
            f"Approve the certificate, then run this again. {detail}"
        )


def write_config(root: Path, certificate: Path, key: Path) -> Path:
    folder = bridge_dir(root)
    folder.mkdir(parents=True, exist_ok=True)
    for name in ("client_body_temp", "proxy_temp", "fastcgi_temp", "uwsgi_temp", "scgi_temp"):
        (folder / name).mkdir(exist_ok=True)
    config = folder / "nginx.conf"
    config.write_text(
        f"""pid {folder / "nginx.pid"};
error_log {folder / "error.log"};
daemon on;
worker_processes 1;

events {{
    worker_connections 256;
}}

stream {{
    log_format aksho '$remote_addr proto=$ssl_preread_protocol bytes=$bytes_sent';
    access_log {folder / "stream.log"} aksho;
    map $ssl_preread_protocol $aksho_upstream {{
        default 127.0.0.1:{INTERNAL_PORT};
        TLSv1.0 127.0.0.1:{TLS_PORT};
        TLSv1.1 127.0.0.1:{TLS_PORT};
        TLSv1.2 127.0.0.1:{TLS_PORT};
        TLSv1.3 127.0.0.1:{TLS_PORT};
    }}
    server {{
        listen 127.0.0.1:{PUBLIC_PORT};
        ssl_preread on;
        proxy_pass $aksho_upstream;
        proxy_connect_timeout 5s;
        proxy_timeout 3600s;
    }}
}}

http {{
    access_log off;
    client_body_temp_path {folder / "client_body_temp"};
    proxy_temp_path {folder / "proxy_temp"};
    fastcgi_temp_path {folder / "fastcgi_temp"};
    uwsgi_temp_path {folder / "uwsgi_temp"};
    scgi_temp_path {folder / "scgi_temp"};
    map $http_upgrade $connection_upgrade {{
        default upgrade;
        '' close;
    }}
    server {{
        listen 127.0.0.1:{TLS_PORT} ssl;
        ssl_certificate {certificate};
        ssl_certificate_key {key};
        ssl_protocols TLSv1.2 TLSv1.3;
        client_max_body_size 0;
        location / {{
            proxy_pass http://127.0.0.1:{INTERNAL_PORT};
            proxy_http_version 1.1;
            proxy_set_header Host $host;
            proxy_set_header Upgrade $http_upgrade;
            proxy_set_header Connection $connection_upgrade;
            proxy_set_header Origin $http_origin;
            proxy_read_timeout 3600s;
            proxy_send_timeout 3600s;
            proxy_buffering off;
            proxy_request_buffering off;
        }}
    }}
}}
""",
        encoding="utf-8",
    )
    return config


def pid_path(root: Path) -> Path:
    return bridge_dir(root) / "nginx.pid"


def our_nginx_pid(root: Path) -> int | None:
    path = pid_path(root)
    if not path.is_file():
        return None
    try:
        pid = int(path.read_text(encoding="utf-8").strip())
    except ValueError:
        return None
    probe = run(["kill", "-0", str(pid)])
    if probe.returncode != 0:
        path.unlink(missing_ok=True)
        return None
    return pid


def listener_pid(port: int) -> int | None:
    result = run(["/usr/sbin/lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"])
    if result.returncode != 0 or not result.stdout.strip():
        return None
    return int(result.stdout.split()[0])


def ensure_started(root: Path) -> None:
    certificate, key = ensure_certs(root)
    trust_ca(root)
    config = write_config(root, certificate, key)
    binary = nginx_bin()
    check = run([binary, "-p", str(bridge_dir(root)), "-c", str(config), "-t"])
    if check.returncode != 0:
        die(f"The local proxy config is invalid.\n{check.stderr.strip()}")

    existing = our_nginx_pid(root)
    if existing is not None:
        reload = run([binary, "-p", str(bridge_dir(root)), "-c", str(config), "-s", "reload"])
        if reload.returncode != 0:
            die(f"Could not reload the local proxy.\n{reload.stderr.strip()}")
        info(f"Local proxy is on 127.0.0.1:{PUBLIC_PORT}.")
        return

    occupant = listener_pid(PUBLIC_PORT)
    if occupant is not None:
        die(f"Port {PUBLIC_PORT} is already in use by process {occupant}. Quit that ComfyUI, then run this again.")
    started = run([binary, "-p", str(bridge_dir(root)), "-c", str(config)])
    if started.returncode != 0:
        log = bridge_dir(root) / "error.log"
        detail = log.read_text(encoding="utf-8") if log.is_file() else started.stderr
        die(f"The local proxy did not start.\n{detail.strip()}")
    if listener_pid(PUBLIC_PORT) is None:
        die("The local proxy exited before it could listen on port 8188.")
    info(f"Local proxy is on 127.0.0.1:{PUBLIC_PORT}. ComfyUI itself uses {INTERNAL_PORT}.")


def stop(root: Path) -> None:
    pid = our_nginx_pid(root)
    if pid is None:
        return
    config = bridge_dir(root) / "nginx.conf"
    binary = nginx_bin()
    if config.is_file():
        run([binary, "-p", str(bridge_dir(root)), "-c", str(config), "-s", "quit"])
    else:
        run(["kill", str(pid)])
    info("Stopped the local proxy.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Proxy HTTP and HTTPS to ComfyUI on port 8188.")
    parser.add_argument("--root", type=Path, default=Path.home() / "AkshoComfy")
    parser.add_argument("--stop", action="store_true")
    args = parser.parse_args()
    root = args.root.expanduser()
    if args.stop:
        stop(root)
        return
    ensure_started(root)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(1)
