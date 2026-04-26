"""
Converts a 3-speaker script to audio using Gemini 2.5 Flash TTS.
At startup, all 4 keys are probed once. Available keys are ranked and
kept in memory for the whole run. Calls are distributed round-robin
across available keys only.
"""

import io
import os
import re
import shutil
import subprocess
import tempfile
import time
import wave

VOICES = {
    "ARISTO": "Charon",   # Deep, measured, authoritative
    "ALBERT": "Puck",     # Warm, playful
    "ISAAC":  "Fenrir",   # Precise, intense
}


def _get_api_keys() -> list:
    return [os.environ[f"AAI_GEMINI_API_KEY_{i}"] for i in range(1, 5)]


def _probe_keys(api_keys: list) -> list:
    """
    Probe each key once with a minimal TTS call.
    Returns ordered list of available (key_index, key) tuples.
    Exhausted keys (429) are dropped entirely.
    """
    from google import genai
    from google.genai import types as gtypes

    config = gtypes.GenerateContentConfig(
        response_modalities=["AUDIO"],
        speech_config=gtypes.SpeechConfig(
            voice_config=gtypes.VoiceConfig(
                prebuilt_voice_config=gtypes.PrebuiltVoiceConfig(voice_name="Charon")
            )
        ),
    )

    available = []
    for i, key in enumerate(api_keys):
        try:
            client = genai.Client(api_key=key)
            client.models.generate_content(
                model="gemini-2.5-flash-preview-tts",
                contents="hi",
                config=config,
            )
            available.append((i, key))
            print(f"  key{i+1}: OK")
        except Exception as e:
            if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                print(f"  key{i+1}: exhausted — skipping")
            else:
                available.append((i, key))
                print(f"  key{i+1}: OK (probe error non-quota)")
    return available


def parse_script(script: str) -> list:
    lines = []
    pattern = re.compile(r'^(ARISTO|ALBERT|ISAAC):\s*(.+)', re.IGNORECASE)
    for line in script.splitlines():
        line = line.strip()
        if not line:
            continue
        m = pattern.match(line)
        if m:
            lines.append((m.group(1).upper(), m.group(2)))
        elif lines:
            lines[-1] = (lines[-1][0], lines[-1][1] + " " + line)
    return lines


def _pcm_to_wav(pcm_data: bytes, sample_rate: int = 24000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_data)
    return buf.getvalue()


def _tts_line(client, speaker: str, text: str) -> bytes:
    from google.genai import types as gtypes
    response = client.models.generate_content(
        model="gemini-2.5-flash-preview-tts",
        contents=text,
        config=gtypes.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=gtypes.SpeechConfig(
                voice_config=gtypes.VoiceConfig(
                    prebuilt_voice_config=gtypes.PrebuiltVoiceConfig(
                        voice_name=VOICES[speaker]
                    )
                )
            ),
        ),
    )
    candidates = response.candidates or []
    if candidates and candidates[0].content:
        for part in candidates[0].content.parts:
            if part.inline_data:
                return part.inline_data.data
    raise RuntimeError(f"No audio for line: {text[:50]}")


def generate_audio(script: str, output_path: str) -> str:
    from google import genai

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    ffmpeg = os.environ.get("FFMPEG_PATH") or shutil.which("ffmpeg") or os.path.expanduser("~/bin/ffmpeg")

    raw_lines = parse_script(script)

    # Merge consecutive lines from the same speaker into one TTS call
    lines = []
    for speaker, text in raw_lines:
        if lines and lines[-1][0] == speaker:
            lines[-1] = (speaker, lines[-1][1] + " " + text)
        else:
            lines.append([speaker, text])
    lines = [(s, t) for s, t in lines]

    print(f"  {len(raw_lines)} lines → {len(lines)} TTS calls")
    print(f"  Probing API keys...")
    available = _probe_keys(_get_api_keys())
    if not available:
        raise RuntimeError("All API keys exhausted for today")
    print(f"  {len(available)}/4 keys available — distributing {len(lines)} calls round-robin")

    wav_files = []
    tmp_dir = tempfile.mkdtemp()
    try:
        for i, (speaker, text) in enumerate(lines):
            success = False
            # Try each available key starting from round-robin position
            for attempt in range(len(available)):
                key_idx, api_key = available[(i + attempt) % len(available)]
                client = genai.Client(api_key=api_key)
                print(f"  [{i+1}/{len(lines)}] {speaker} (key{key_idx+1}): {text[:50]}...")
                try:
                    pcm = _tts_line(client, speaker, text)
                    wav_data = _pcm_to_wav(pcm)
                    wav_path = os.path.join(tmp_dir, f"{i:03d}_{speaker}.wav")
                    with open(wav_path, "wb") as f:
                        f.write(wav_data)
                    wav_files.append(wav_path)
                    success = True
                    break
                except Exception as e:
                    is_quota = "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e)
                    if is_quota:
                        print(f"    key{key_idx+1} exhausted mid-run — trying next key")
                        available.pop((i + attempt) % len(available))
                        if not available:
                            raise RuntimeError("All API keys exhausted mid-run")
                    else:
                        wait = 10 * (attempt + 1)
                        print(f"    Error, retrying in {wait}s... ({e})")
                        time.sleep(wait)
            if not success:
                raise RuntimeError(f"Failed to generate TTS for line {i+1} after trying all keys")
            time.sleep(5)  # rate limit

        list_file = os.path.join(tmp_dir, "concat.txt")
        with open(list_file, "w") as f:
            for wav in wav_files:
                f.write(f"file '{wav}'\n")

        subprocess.run(
            [ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", list_file,
             "-q:a", "2", output_path],
            check=True, capture_output=True,
        )
    finally:
        import shutil as _shutil
        _shutil.rmtree(tmp_dir, ignore_errors=True)

    print(f"  Audio saved: {output_path}")
    return output_path
