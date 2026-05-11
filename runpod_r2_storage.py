"""Minimal R2 client — download/upload via boto3.

R2 CDN bloqueia urllib User-Agent default (HTTP 403). Sempre via boto3
S3 client com R2 endpoint pra qualquer download de URL nosso.
"""
import os
import boto3
from urllib.parse import urlparse

_S3 = None


def _client():
    global _S3
    if _S3 is None:
        _S3 = boto3.client(
            "s3",
            endpoint_url=os.environ["R2_ENDPOINT"],
            aws_access_key_id=os.environ["R2_ACCESS_KEY"],
            aws_secret_access_key=os.environ["R2_SECRET_KEY"],
            region_name="auto",
        )
    return _S3


def _public_url_to_key(url: str):
    """Converte URL pública R2 (pub-XXX.r2.dev/path) → key (path)."""
    public_base = os.environ.get("R2_PUBLIC_URL", "").rstrip("/")
    if public_base and url.startswith(public_base + "/"):
        return url[len(public_base) + 1:]
    p = urlparse(url)
    if p.hostname and p.hostname.endswith(".r2.dev"):
        return p.path.lstrip("/")
    return None


def download(url_or_key: str, local_path: str) -> str:
    """Download from R2. Aceita URL pública ou key direto."""
    if url_or_key.startswith("http"):
        key = _public_url_to_key(url_or_key)
        if key is None:
            # URL externa (não nosso R2) — fallback urllib com UA custom
            import urllib.request
            req = urllib.request.Request(
                url_or_key,
                headers={"User-Agent": "Mozilla/5.0 (RunPod-YingMusic-SVC)"},
            )
            with urllib.request.urlopen(req) as resp, open(local_path, "wb") as f:
                f.write(resp.read())
            return local_path
    else:
        key = url_or_key
    _client().download_file(os.environ["R2_BUCKET"], key, local_path)
    return local_path


def upload(local_path: str, key: str, content_type: str = "audio/mpeg") -> str:
    """Upload local file to R2; return public URL."""
    _client().upload_file(
        local_path,
        os.environ["R2_BUCKET"],
        key,
        ExtraArgs={"ContentType": content_type},
    )
    public_base = os.environ["R2_PUBLIC_URL"].rstrip("/")
    return f"{public_base}/{key}"
