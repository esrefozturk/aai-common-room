"""
Renders a 1920x1080 video: AI-generated cover image + audio.
Cover includes character silhouettes, AAI branding, and episode-specific speech bubbles.
"""

import os
import shutil
import subprocess


_FFMPEG = os.environ.get("FFMPEG_PATH") or shutil.which("ffmpeg") or os.path.expanduser("~/bin/ffmpeg")


def extract_key_phrases(script: str, book_title: str) -> dict:
    """Use Gemini to pick the hookiest quote per character for the thumbnail."""
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=os.environ["AAI_GEMINI_API_KEY_1"])
    prompt = (
        f"From this podcast script about \"{book_title}\", pick the single best thumbnail quote for each character.\n\n"
        f"Each quote must:\n"
        f"- Come from ANYWHERE in the script, not just the intro\n"
        f"- Be hooky enough to make someone stop scrolling on YouTube\n"
        f"- Sound like that specific character's personality:\n"
        f"  ARISTO: a sharp philosophical question or big idea\n"
        f"  ALBERT: something excited, surprising, or a wild connection\n"
        f"  ISAAC: something blunt, skeptical, or cutting\n"
        f"- Be 8-12 words max (truncate if needed)\n\n"
        f"Reply in exactly this format, nothing else:\n"
        f"ARISTO: <quote>\n"
        f"ALBERT: <quote>\n"
        f"ISAAC: <quote>\n\n"
        f"Script:\n{script}"
    )
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            max_output_tokens=256,
            thinking_config=types.ThinkingConfig(thinking_budget=0),
        ),
    )
    text = (response.text or "").strip()
    result = {}
    for line in text.splitlines():
        for speaker in ("ARISTO", "ALBERT", "ISAAC"):
            if line.upper().startswith(speaker + ":"):
                result[speaker] = line[len(speaker)+1:].strip()
    return result


def generate_cover(title: str, output_path: str, script: str = "") -> str:
    """Generate AI cover image using Gemini image generation."""
    from google import genai
    from google.genai import types

    phrases = {"ARISTO": "Was he a creator or just a coward?",
               "ALBERT": "The monster just wanted a friend!",
               "ISAAC": "Bad science, bad outcomes. Simple."}
    if script:
        try:
            phrases = extract_key_phrases(script, title)
            print(f"  Key phrases: {phrases}")
        except Exception as e:
            print(f"  Warning: could not extract phrases ({e}), using defaults")

    aristo_quote = phrases.get("ARISTO", "")[:80]
    albert_quote = phrases.get("ALBERT", "")[:80]
    isaac_quote = phrases.get("ISAAC", "")[:80]

    prompt = (
        f"A YouTube podcast thumbnail, 1920x1080, for an episode about \"{title}\".\n\n"
        f"Scene: Three stylized characters sitting around a round table in a cozy, dimly lit common room. "
        f"All three wear modern casual academic clothing — jeans, shirts, blazers. No robes, no wigs, no historical costumes. "
        f"Their faces are distinct from each other. "
        f"Left (Aristo): broad forehead, short beard, calm wise eyes. "
        f"Center (Albert): bushy eyebrows, expressive eyes, wild hair. "
        f"Right (Isaac): long nose, sharp focused gaze, straight hair. "
        f"The three faces must look clearly different from each other. "
        f"They are leaning in, mid-discussion. "
        f"No name labels on the characters. "
        f"On the table between them, a dramatic illustrated scene from \"{title}\" — like a vivid book illustration or artwork depicting a key moment from the story — as if they are all looking at and discussing it.\n\n"
        f"Text and branding:\n"
        f"- Bold gold 'AAI Common Room' text at the top\n"
        f"- Three speech bubbles, one per character:\n"
        f"  Aristo (left): \"{aristo_quote}\"\n"
        f"  Albert (center): \"{albert_quote}\"\n"
        f"  Isaac (right): \"{isaac_quote}\"\n\n"
        f"Style:\n"
        f"- Deep navy blue background (#1a1a2e), gold accent colors\n"
        f"- Stylized illustration, no photorealistic faces\n"
        f"- High contrast, eye-catching thumbnail aesthetic"
    )

    client = genai.Client(api_key=os.environ["AAI_GEMINI_API_KEY_1"])
    response = client.models.generate_content(
        model="gemini-3.1-flash-image-preview",
        contents=prompt,
        config=types.GenerateContentConfig(
            response_modalities=["IMAGE", "TEXT"],
            image_config=types.ImageConfig(aspect_ratio="16:9"),
        ),
    )

    parts = []
    if response.candidates and response.candidates[0].content and response.candidates[0].content.parts:
        parts = response.candidates[0].content.parts

    for part in parts:
        if hasattr(part, "inline_data") and part.inline_data:
            with open(output_path, "wb") as f:
                f.write(part.inline_data.data)
            print(f"  Cover saved: {output_path}")
            return output_path

    raise RuntimeError("No image in Gemini response")


def generate_video(audio_path: str, cover_path: str, output_path: str):
    cmd = [
        _FFMPEG, "-y",
        "-loop", "1", "-i", cover_path,
        "-i", audio_path,
        "-vf", "scale=1920:1080,format=yuv420p",
        "-map", "0:v", "-map", "1:a",
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-c:a", "aac", "-b:a", "192k",
        "-shortest",
        output_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed:\n{result.stderr}")
    print(f"  Video saved: {output_path}")
