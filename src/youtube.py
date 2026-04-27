"""
Uploads AAI Common Room episodes and shorts to YouTube.
Token stored in AWS Secrets Manager as 'aai-common-room/youtube'.
Auto-refreshes and saves back on each run.
"""

import json
import os

SCOPES = [
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/youtube.upload",
]
TOKEN_FILE = "token.json"
CREDENTIALS_FILE = "credentials.json"
SECRET_ID = "aai-common-room/youtube"


def _clean_title(book_title: str) -> str:
    """Return clean display title, stripping subtitles and suffixes."""
    import re
    t = book_title
    # Strip catalog metadata (e.g. ": $b [Peter and Wendy]")
    t = re.sub(r'\s*:\s*\$b\s*.*', '', t)
    # Split on ; or : and take the first part
    for sep in (';', ':'):
        parts = t.split(sep)
        if len(parts) > 1:
            t = parts[0]
    # Strip "— Complete / Volume / Part ..." and ", Complete / a novel / ..."
    t = re.sub(r'\s*—\s*(Complete|Volume|Part).*', '', t, flags=re.IGNORECASE)
    t = re.sub(r',\s*(Complete|a|an|the)\s*\w*$', '', t, flags=re.IGNORECASE)
    t = t.strip()
    # Fix all-lowercase titles
    if t == t.lower():
        t = t.title()
        t = re.sub(r"(\w)'(\w)", lambda m: m.group(1) + "'" + m.group(2).lower(), t)
    return t


def _get_youtube_client():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    creds = None

    # Load token from local file or Secrets Manager
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    else:
        try:
            import boto3
            client = boto3.client("secretsmanager", region_name=os.environ.get("AWS_DEFAULT_REGION", "us-east-1"))
            token_data = json.loads(client.get_secret_value(SecretId=SECRET_ID)["SecretString"])
            with open(TOKEN_FILE, "w") as f:
                json.dump(token_data, f)
            creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
            print("  Loaded YouTube token from Secrets Manager.")
        except Exception as e:
            raise RuntimeError(f"No token.json and Secrets Manager failed: {e}")

    if creds and creds.expired and creds.refresh_token:
        print("  Refreshing YouTube token...")
        creds.refresh(Request())
        with open(TOKEN_FILE, "w") as f:
            f.write(creds.to_json())
        _save_token(creds)

    return build("youtube", "v3", credentials=creds)


def _save_token(creds):
    try:
        import boto3
        client = boto3.client("secretsmanager", region_name=os.environ.get("AWS_DEFAULT_REGION", "us-east-1"))
        client.put_secret_value(SecretId=SECRET_ID, SecretString=creds.to_json())
        print("  YouTube token saved to Secrets Manager.")
    except Exception as e:
        print(f"  Warning: could not save token to Secrets Manager: {e}")


def generate_metadata(book_title: str, script: str) -> dict:
    """Use Gemini to generate YouTube title, description, and tags."""
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=os.environ["AAI_GEMINI_API_KEY_1"])
    prompt = (
        f"Generate YouTube metadata for an episode of 'The AAI Common Room' podcast about the book \"{book_title}\".\n\n"
        f"Script excerpt:\n{script[:3000]}\n\n"
        f"Return a JSON object with exactly these fields:\n"
        f'{{\n'
        f'  "title": "engaging YouTube title, max 70 chars, include the book name",\n'
        f'  "description": "3-4 sentence episode description. What the episode covers, key themes discussed. End with: The AAI Common Room — Aristo, Albert, and Isaac discuss books, history, and ideas.\\n\\n#Books #BookPodcast #AAICommonRoom",\n'
        f'  "tags": ["list", "of", "10-15", "relevant", "tags", "include AAICommonRoom", "Books", "Podcast"]\n'
        f"}}\n\n"
        f"Output only valid JSON, nothing else."
    )
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            max_output_tokens=1024,
            thinking_config=types.ThinkingConfig(thinking_budget=0),
        ),
    )
    text = (response.text or "").strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text.strip())


def upload_video(video_path: str, cover_path: str, book_title: str, script: str, privacy: str = "public") -> str:
    """Upload episode to YouTube. Returns video URL."""
    from googleapiclient.http import MediaFileUpload

    youtube = _get_youtube_client()

    print("  Generating metadata...")
    metadata = generate_metadata(book_title, script)
    print(f"  Title: {metadata['title']}")

    body = {
        "snippet": {
            "title": metadata["title"],
            "description": metadata["description"],
            "tags": metadata.get("tags", []),
            "categoryId": "27",  # Education
            "defaultLanguage": "en",
            "defaultAudioLanguage": "en",
        },
        "status": {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": False,
            "embeddable": True,
            "publicStatsViewable": True,
            "containsSyntheticMedia": True,
        },
    }

    print(f"  Uploading: {video_path}")
    media = MediaFileUpload(video_path, chunksize=4 * 1024 * 1024, resumable=True)
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"  Upload progress: {int(status.progress() * 100)}%")

    video_id = response["id"]
    url = f"https://youtube.com/watch?v={video_id}"
    print(f"  Uploaded: {url}")

    if cover_path and os.path.exists(cover_path):
        try:
            from PIL import Image
            import tempfile
            with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
                thumb_jpg = tmp.name
            img = Image.open(cover_path).convert("RGB")
            img.save(thumb_jpg, "JPEG", quality=85, optimize=True)
            youtube.thumbnails().set(
                videoId=video_id,
                media_body=MediaFileUpload(thumb_jpg, mimetype="image/jpeg")
            ).execute()
            os.remove(thumb_jpg)
            print("  Thumbnail set.")
        except Exception as e:
            print(f"  Thumbnail upload failed: {e}")

    # YouTube ignores containsSyntheticMedia on insert — must update separately
    youtube.videos().update(
        part="status",
        body={"id": video_id, "status": {"containsSyntheticMedia": True}},
    ).execute()
    print("  containsSyntheticMedia set.")

    return url


def upload_short(video_path: str, cover_path: str, book_title: str, privacy: str = "public") -> str:
    """Upload short to YouTube. Returns video URL."""
    from googleapiclient.http import MediaFileUpload

    youtube = _get_youtube_client()
    clean = _clean_title(book_title)

    title = f"{clean} in 30 Seconds | #Shorts | AAI Common Room"
    description = (
        f"A quick take on \"{clean}\" from The AAI Common Room.\n\n"
        f"Watch the full episode on our channel!\n\n"
        f"#Shorts #Books #BookTok #AAICommonRoom #BookSummary"
    )

    body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": ["Shorts", "Books", "BookSummary", "AAICommonRoom", "BookTok", clean],
            "categoryId": "27",
            "defaultLanguage": "en",
            "defaultAudioLanguage": "en",
        },
        "status": {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": False,
            "embeddable": True,
            "publicStatsViewable": True,
            "containsSyntheticMedia": True,
        },
    }

    print(f"  Uploading short: {video_path}")
    media = MediaFileUpload(video_path, chunksize=4 * 1024 * 1024, resumable=True)
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"  Short upload progress: {int(status.progress() * 100)}%")

    video_id = response["id"]
    url = f"https://youtube.com/watch?v={video_id}"
    print(f"  Short uploaded: {url}")

    if cover_path and os.path.exists(cover_path):
        try:
            from PIL import Image
            import tempfile
            with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
                thumb_jpg = tmp.name
            img = Image.open(cover_path).convert("RGB")
            img.save(thumb_jpg, "JPEG", quality=85, optimize=True)
            youtube.thumbnails().set(
                videoId=video_id,
                media_body=MediaFileUpload(thumb_jpg, mimetype="image/jpeg")
            ).execute()
            os.remove(thumb_jpg)
            print("  Short thumbnail set.")
        except Exception as e:
            print(f"  Short thumbnail upload failed: {e}")

    youtube.videos().update(
        part="status",
        body={"id": video_id, "status": {"containsSyntheticMedia": True}},
    ).execute()
    print("  containsSyntheticMedia set.")

    return url


def notify_telegram(book_title: str, episode_url: str, short_url: str):
    """Send Telegram notification with episode links."""
    try:
        import boto3, requests as req
        region = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
        secret = json.loads(
            boto3.client("secretsmanager", region_name=region)
            .get_secret_value(SecretId="sazaktechs/telegram")["SecretString"]
        )
        token = secret["bot_token"]
        chat_id = secret["chat_id"]
        clean = _clean_title(book_title)
        msg = (
            f"✅ <b>AAI Common Room — New Episode</b>\n\n"
            f"<b>Book:</b> {clean}\n"
            f"<b>Episode:</b> {episode_url}\n"
            f"<b>Short:</b> {short_url}"
        )
        req.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": msg, "parse_mode": "HTML"},
            timeout=10,
        )
        print("  Telegram notification sent.")
    except Exception as e:
        print(f"  Telegram notification failed: {e}")
