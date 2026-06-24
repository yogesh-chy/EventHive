import threading

import boto3
from botocore.client import Config
from django.conf import settings

_client_lock = threading.Lock()
_client = None


def get_s3_client():
    global _client
    if _client is not None:
        return _client
    
    with _client_lock:
        if _client is None:
            _client = boto3.client(
                "s3",
                # Leave AWS_S3_ENDPOINT_URL unset for real AWS S3. Set it
                # (e.g. "https://<account_id>.r2.cloudflarestorage.com") to
                # point this at Cloudflare R2 or MinIO instead -- nothing
                # else in this module needs to change either way
                endpoint_url=getattr(settings, "AWS_S3_ENDPOINT_URL", None),
                aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
                aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
                region_name=getattr(settings, "AWS_S3_REGION_NAME", "auto"),
                config=Config(signature_version="s3v4")
            )
        return _client

def build_ticket_pdf_key(*, org_slug: str, event_slug: str, ticket_id) -> str:
    """
    Deterministic, tenant-namespaced key.

    Deterministic matters for idempotency: a retried generate_ticket_assets_task
    (e.g. it succeeded uploading but crashed before saving Ticket.pdf_url)
    overwrites the *same* object instead of orphaning a new one under a
    random key on every retry.

    Namespaced by org + event matters for multi-tenancy: prevents any
    collision across tenants and makes future per-tenant lifecycle/cleanup
    rules (e.g. "delete tickets/{org}/{event}/* 90 days post-event") easy
    to write.
    """
    return f"tickets/{org_slug}/{event_slug}/{ticket_id}.pdf"

def upload_bytes(*, key: str, data: bytes, content_type: str = "application/pdf") -> None:
    client = get_s3_client()
    client.put_object(
        Bucket=settings.AWS_STORAGE_BUCKET_NAME,
        Key=key,
        Body=data,
        ContentType=content_type,
        ServerSideEncryption="AES256"
    )

def generate_presigned_url(*, key: str, expires_in: int = 3600) -> str:
    if not key:
        return ""
    client = get_s3_client()
    return client.generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.AWS_STORAGE_BUCKET_NAME, "Key": key},
        ExpiresIn=expires_in
    )