"""Minimal R2 client — download input audio + upload result."""
import os
import boto3
from urllib.parse import urlparse
import urllib.request

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


def download(url_or_key: str, local_path: str) -> str:
    """Download from R2 (public URL or s3 key) to local_path."""
    if url_or_key.startswith("http"):
        urllib.request.urlretrieve(url_or_key, local_path)
    else:
        _client().download_file(os.environ["R2_BUCKET"], url_or_key, local_path)
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
