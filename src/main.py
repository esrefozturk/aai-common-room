"""
The AAI Common Room — pipeline runner.
Local: python -m src.main "Frankenstein" [--duration 60] [--upload] [--privacy unlisted]
ECS:   run_pipeline() — auto-selects next unpublished novel from Gutenberg popular list.
"""

import json
import os
import sys
import urllib.parse
import urllib.request
import requests

from src.script_generator import generate_script
from src.tts import generate_audio
from src.video import generate_cover, generate_video
from src.short import generate_short
from src.youtube import upload_video, upload_short

GUTENBERG_SEARCH = "https://gutendex.com/books?search={}&languages=en"
GUTENBERG_POPULAR = "https://gutendex.com/books?sort=popular&languages=en"
OUTPUT_DIR = "output"
DURATION_MINUTES = 60
PRIVACY = "unlisted"


def _get_with_retry(url: str, **kwargs) -> requests.Response:
    """GET with exponential backoff on failure."""
    for attempt in range(6):
        try:
            r = requests.get(url, headers={"User-Agent": "aai-common-room/1.0"}, **kwargs)
            r.raise_for_status()
            return r
        except Exception as e:
            if attempt == 5:
                raise
            wait = 2 ** attempt  # 1, 2, 4, 8, 16s
            print(f"  Fetch failed ({e}), retrying in {wait}s...")
            import time; time.sleep(wait)


def fetch_book(title: str) -> tuple[str, str]:
    """Search Gutendex and return (exact_title, plain_text)."""
    url = GUTENBERG_SEARCH.format(urllib.parse.quote(title))
    data = _get_with_retry(url).json()

    if not data["results"]:
        raise RuntimeError(f"Book not found: {title}")

    book = data["results"][0]
    exact_title = book["title"]
    text_url = book["formats"].get("text/plain; charset=utf-8") or \
               book["formats"].get("text/plain; charset=us-ascii") or \
               book["formats"].get("text/plain")

    if not text_url:
        raise RuntimeError(f"No plain text format for: {exact_title}")

    print(f"  Fetching: {exact_title}")
    text = _get_with_retry(text_url).text

    return exact_title, text


def run(book_title: str, duration_minutes: int = 10, upload: bool = False, privacy: str = "public"):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    slug = book_title.split(";")[0].split(",")[0].strip().lower().replace(" ", "_")

    audio_path = os.path.join(OUTPUT_DIR, f"{slug}.mp3")
    cover_path = os.path.join(OUTPUT_DIR, f"{slug}_cover.png")
    video_path = os.path.join(OUTPUT_DIR, f"{slug}.mp4")
    script_path = os.path.join(OUTPUT_DIR, f"{slug}_script.txt")

    print(f"\n=== The AAI Common Room: {book_title} ===")

    print("\n[1/5] Fetching book from Project Gutenberg...")
    exact_title, book_text = fetch_book(book_title)
    print(f"  Got {len(book_text):,} characters")

    print("\n[2/5] Generating script...")
    script = generate_script(exact_title, book_text, duration_minutes=duration_minutes)
    with open(script_path, "w") as f:
        f.write(script)
    print(f"  Script ({len(script.split())} words):\n")
    print(script)

    print("\n[3/5] Generating audio...")
    generate_audio(script, audio_path)

    print("\n[4/5] Rendering video...")
    generate_cover(exact_title, cover_path, script=script)
    generate_video(audio_path, cover_path, video_path)

    print("\n[5/5] Generating short...")
    short_path = generate_short(exact_title, book_text, OUTPUT_DIR)
    short_cover_path = os.path.join(OUTPUT_DIR, f"{slug}_short_cover.png")

    if upload:
        print("\n[6/6] Uploading to YouTube...")
        video_url = upload_video(video_path, cover_path, exact_title, script, privacy=privacy)
        short_url = upload_short(short_path, short_cover_path, exact_title, privacy=privacy)
        print(f"\n  Episode: {video_url}")
        print(f"  Short:   {short_url}")

    print(f"\nDone! Output: {video_path}")


def _pick_next_book(published: set) -> tuple[str, str] | None:
    """
    Fetch Gutenberg popular list, filter to 'Category: Novels',
    return (exact_title, plain_text) for first unpublished book.
    Returns None if all known novels are published.
    """
    page_url = GUTENBERG_POPULAR
    while page_url:
        data = _get_with_retry(page_url).json()
        for book in data.get("results", []):
            bookshelves = book.get("bookshelves", [])
            if not any("Category: Novels" in s for s in bookshelves):
                continue
            exact_title = book["title"]
            if exact_title in published:
                print(f"  Skipping (published): {exact_title}")
                continue
            text_url = (
                book["formats"].get("text/plain; charset=utf-8") or
                book["formats"].get("text/plain; charset=us-ascii") or
                book["formats"].get("text/plain")
            )
            if not text_url:
                print(f"  Skipping (no plain text): {exact_title}")
                continue
            print(f"  Selected: {exact_title}")
            text = _get_with_retry(text_url).text
            return exact_title, text
        page_url = data.get("next")
    return None


def run_pipeline():
    """Entry point for ECS: auto-select next book, generate, upload, mark done."""
    from src.state import get_published, mark_published

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    print("\n=== The AAI Common Room — Daily Pipeline ===")

    print("\n[1/6] Loading published books from S3...")
    published = get_published()
    print(f"  {len(published)} books published so far")

    print("\n[2/6] Selecting next novel from Gutenberg popular list...")
    result = _pick_next_book(published)
    if result is None:
        print("  All known novels already published — nothing to do.")
        return
    exact_title, book_text = result
    print(f"  Got {len(book_text):,} characters")

    slug = exact_title.split(";")[0].split(",")[0].strip().lower().replace(" ", "_")
    audio_path = os.path.join(OUTPUT_DIR, f"{slug}.mp3")
    cover_path = os.path.join(OUTPUT_DIR, f"{slug}_cover.png")
    video_path = os.path.join(OUTPUT_DIR, f"{slug}.mp4")
    script_path = os.path.join(OUTPUT_DIR, f"{slug}_script.txt")
    short_cover_path = os.path.join(OUTPUT_DIR, f"{slug}_short_cover.png")

    print(f"\n[3/6] Generating script ({DURATION_MINUTES} min)...")
    script = generate_script(exact_title, book_text, duration_minutes=DURATION_MINUTES)
    with open(script_path, "w") as f:
        f.write(script)
    print(f"  Script: {len(script.split())} words")

    print("\n[4/6] Generating audio...")
    generate_audio(script, audio_path)

    print("\n[5/6] Rendering video + short...")
    generate_cover(exact_title, cover_path, script=script)
    generate_video(audio_path, cover_path, video_path)
    short_path = generate_short(exact_title, book_text, OUTPUT_DIR)

    print(f"\n[6/6] Uploading to YouTube ({PRIVACY})...")
    video_url = upload_video(video_path, cover_path, exact_title, script, privacy=PRIVACY)
    short_url = upload_short(short_path, short_cover_path, exact_title, privacy=PRIVACY)
    print(f"  Episode: {video_url}")
    print(f"  Short:   {short_url}")

    mark_published(exact_title)
    print(f"\nDone! {exact_title}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("title", nargs="*", default=["Frankenstein"])
    parser.add_argument("--duration", type=int, default=10)
    parser.add_argument("--upload", action="store_true", help="Upload to YouTube after generation")
    parser.add_argument("--privacy", default="public", choices=["public", "unlisted", "private"])
    args = parser.parse_args()
    run(" ".join(args.title), duration_minutes=args.duration, upload=args.upload, privacy=args.privacy)
