"""
Tracks published books in S3.
State file: s3://{S3_BUCKET}/state.json
Format: {"published": ["Frankenstein", "Moby Dick; Or, The Whale", ...]}
"""

import json
import os


def _s3():
    import boto3
    return boto3.client("s3", region_name=os.environ.get("AWS_DEFAULT_REGION", "us-east-1"))


def _bucket() -> str:
    return os.environ["AAI_S3_BUCKET"]


def get_published() -> set:
    """Return set of exact book titles already published."""
    try:
        obj = _s3().get_object(Bucket=_bucket(), Key="state.json")
        data = json.loads(obj["Body"].read())
        return set(data.get("published", []))
    except Exception as e:
        if "NoSuchKey" in str(e) or "NoSuchBucket" in str(e):
            return set()
        raise


def mark_published(exact_title: str):
    """Add a book title to the published set and save."""
    published = get_published()
    published.add(exact_title)
    _s3().put_object(
        Bucket=_bucket(),
        Key="state.json",
        Body=json.dumps({"published": sorted(published)}, indent=2),
        ContentType="application/json",
    )
    print(f"  Marked as published: {exact_title}")
