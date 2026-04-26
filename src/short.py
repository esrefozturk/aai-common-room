"""
Generates a 30-second YouTube Short for each book episode.
- Single narrator voice (Aristo)
- Hook-first script: first words must grab attention immediately
- Cover image features the hook text prominently
- 1080x1920 vertical format
"""

import io
import os
import shutil
import subprocess
import tempfile
import time
import wave

_FFMPEG = os.environ.get("FFMPEG_PATH") or shutil.which("ffmpeg") or os.path.expanduser("~/bin/ffmpeg")
_VOICE = "Charon"  # Aristo's voice


def generate_short_script(book_title: str, book_text: str) -> tuple[str, str]:
    """
    Generate a 30-second short script.
    Returns (hook, full_script) where hook is the opening phrase.
    """
    import time as _time
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=os.environ["AAI_GEMINI_API_KEY_1"])
    prompt = (
        f"Write a 30-second spoken script (exactly 70-80 words) about the book \"{book_title}\" for a YouTube Short.\n\n"
        f"Book content:\n{book_text[:5000]}\n\n"
        f"Rules:\n"
        f"- The FIRST 5-8 words must be a jaw-dropping hook — the most shocking, surprising, or controversial thing from the book\n"
        f"- After the hook, briefly explain what happens and why it matters\n"
        f"- Simple conversational English — no fancy words\n"
        f"- End with a natural, creative call to action: tell them to watch the full podcast episode, like, comment, and subscribe — but make it feel unique and fun, not generic. Different every time.\n"
        f"- Output ONLY the narration text, nothing else\n\n"
        f"Example hook style: 'A teenager wrote this book on a dare...' or 'He created life, then ran away from it...'"
    )

    for attempt in range(5):
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                max_output_tokens=512,
                thinking_config=types.ThinkingConfig(thinking_budget=0),
            ),
        )
        text = (response.text or "").strip()
        if text:
            # Extract hook = first sentence or first 8 words
            first_sentence = text.split(".")[0].strip()
            words = first_sentence.split()
            hook = " ".join(words[:8]) + ("..." if len(words) > 8 else "")
            return hook, text
        reason = response.candidates[0].finish_reason if response.candidates else "unknown"
        print(f"  Empty short script (reason: {reason}), retrying in 15s...")
        _time.sleep(15)

    raise RuntimeError("Failed to generate short script after 5 attempts")


def generate_short_audio(script: str, output_path: str) -> str:
    """Single-voice TTS for the short."""
    from google import genai
    from google.genai import types

    import random
    keys = [os.environ[f"AAI_GEMINI_API_KEY_{i}"] for i in range(1, 5)]
    client = genai.Client(api_key=random.choice(keys))
    response = client.models.generate_content(
        model="gemini-2.5-flash-preview-tts",
        contents=script,
        config=types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=_VOICE)
                )
            ),
        ),
    )
    candidates = response.candidates or []
    if candidates and candidates[0].content:
        for part in candidates[0].content.parts:
            if part.inline_data:
                buf = io.BytesIO()
                with wave.open(buf, "wb") as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(2)
                    wf.setframerate(24000)
                    wf.writeframes(part.inline_data.data)
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                    tmp.write(buf.getvalue())
                    wav_path = tmp.name
                try:
                    subprocess.run(
                        [_FFMPEG, "-y", "-i", wav_path, "-q:a", "2", output_path],
                        check=True, capture_output=True,
                    )
                finally:
                    os.remove(wav_path)
                return output_path
    raise RuntimeError("No audio data in Gemini TTS response")


def generate_short_cover(hook: str, book_title: str, output_path: str):
    """Generate a vertical short cover with the hook text as the hero element."""
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=os.environ["AAI_GEMINI_API_KEY_1"])
    prompt = (
        f"A YouTube Shorts thumbnail, 1080x1920 vertical format, for a book short about \"{book_title}\".\n\n"
        f"The dominant element is this hook text displayed in large, bold, eye-catching typography:\n"
        f"\"{hook}\"\n\n"
        f"Design:\n"
        f"- Deep navy background\n"
        f"- The hook text takes up the top 60% of the image in huge bold gold/white letters\n"
        f"- Dramatic illustration or silhouette related to the book content in the lower half\n"
        f"- Small 'AAI Common Room' branding at the bottom\n"
        f"- High contrast, designed to stop someone scrolling\n"
        f"- No faces, stylized illustration only"
    )

    response = client.models.generate_content(
        model="gemini-3.1-flash-image-preview",
        contents=prompt,
        config=types.GenerateContentConfig(
            response_modalities=["IMAGE", "TEXT"],
            image_config=types.ImageConfig(aspect_ratio="9:16"),
        ),
    )

    for part in (response.candidates[0].content.parts
                 if response.candidates and response.candidates[0].content else []):
        if hasattr(part, "inline_data") and part.inline_data:
            with open(output_path, "wb") as f:
                f.write(part.inline_data.data)
            print(f"  Short cover saved: {output_path}")
            return output_path

    raise RuntimeError("No image in Gemini response for short cover")


def generate_short_video(audio_path: str, cover_path: str, output_path: str):
    """Render 1080x1920 vertical video."""
    cmd = [
        _FFMPEG, "-y",
        "-loop", "1", "-i", cover_path,
        "-i", audio_path,
        "-vf", "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2,format=yuv420p",
        "-map", "0:v", "-map", "1:a",
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-c:a", "aac", "-b:a", "192k",
        "-shortest",
        output_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed:\n{result.stderr}")
    print(f"  Short video saved: {output_path}")


def generate_short(book_title: str, book_text: str, output_dir: str) -> str:
    """Full short pipeline: script → audio → cover → video. Returns video path."""
    slug = book_title.split(";")[0].split(",")[0].strip().lower().replace(" ", "_")[:40]
    audio_path = os.path.join(output_dir, f"{slug}_short.mp3")
    cover_path = os.path.join(output_dir, f"{slug}_short_cover.png")
    video_path = os.path.join(output_dir, f"{slug}_short.mp4")
    script_path = os.path.join(output_dir, f"{slug}_short_script.txt")

    print("\nGenerating short script...")
    hook, script = generate_short_script(book_title, book_text)
    print(f"  Hook: {hook}")
    print(f"  Script ({len(script.split())} words): {script[:100]}...")
    with open(script_path, "w") as f:
        f.write(f"HOOK: {hook}\n\n{script}")

    print("Generating short audio...")
    generate_short_audio(script, audio_path)

    print("Generating short cover...")
    generate_short_cover(hook, book_title, cover_path)

    print("Rendering short video...")
    generate_short_video(audio_path, cover_path, video_path)

    print(f"  Short done: {video_path}")
    return video_path
