"""
Generates a podcast script for a book discussion.
Three friends: ARISTO, ALBERT, ISAAC — talking about a book they've all read.
"""

import os
from google import genai
from google.genai import types


def generate_script(book_title: str, book_text: str, duration_minutes: int = 10) -> str:
    client = genai.Client(api_key=os.environ["AAI_GEMINI_API_KEY_1"])

    words_per_minute = 130
    target_words = duration_minutes * words_per_minute
    word_range = f"{target_words - 100}-{target_words + 100}"
    book_chars = min(len(book_text), 12000 * (duration_minutes // 10))

    prompt = (
        f"Write a {duration_minutes}-minute podcast script where three very smart, very well-read friends casually discuss the book \"{book_title}\".\n\n"
        f"CRITICAL: The script MUST be exactly {word_range} words of dialogue. Count carefully. Do NOT stop early. "
        f"If you finish covering the book before reaching the word count, go deeper — explore themes, debate interpretations, make connections to other works, dig into specific scenes and quotes. Keep going until you hit {target_words} words.\n\n"
        f"Book content (use this as your source):\n{book_text[:book_chars]}\n\n"
        f"The three friends:\n"
        f"- ARISTO: Curious, asks good questions, sometimes challenges the others. Drives the conversation forward. Occasionally drops a big idea but never lectures.\n"
        f"- ALBERT: Enthusiastic, makes unexpected connections, gets excited about ideas. Playful. Sometimes goes on a tangent but it's always interesting.\n"
        f"- ISAAC: Blunt, direct, slightly skeptical. Cuts through the fluff. Occasionally surprised by something and admits it. Disagrees with Albert a lot.\n\n"
        f"Format every line strictly as:\n"
        f"ARISTO: [dialogue]\n"
        f"ALBERT: [dialogue]\n"
        f"ISAAC: [dialogue]\n\n"
        f"Structure:\n"
        f"1. INTRO (3-4 exchanges): Aristo welcomes everyone to the AAI Common Room and introduces today's book \"{book_title}\". All three briefly say they're here and drop one teaser reaction to the book — something that makes the listener want to keep listening. Natural, warm, like a real show opening.\n"
        f"2. MAIN DISCUSSION: Walk through the most important parts of the book — what happens, key characters, moments that matter. The listener should understand the full arc by the end. React to specific scenes, quotes — make it feel like they actually read it.\n"
        f"3. OUTRO + CTA (4-5 exchanges): Wind the conversation down naturally. Then one of them (rotate who) asks the audience something — a unique, specific question about this book or its themes that makes people want to comment (not generic 'what did you think?'). Another one mentions subscribing — but in a creative, non-cringe way that fits their personality. Different every episode.\n\n"
        f"Rules:\n"
        f"- Talk like actual friends, not professors. Casual language. Interruptions are fine. Short reactions are fine ('wait, really?' / 'exactly!' / 'no no no').\n"
        f"- Never list facts. Always put information inside a reaction or an opinion.\n"
        f"- Keep energy high — if a topic is getting flat, one of them changes the angle.\n"
        f"- No stage directions, no labels — pure dialogue only.\n"
        f"- Use simple, everyday English. No fancy vocabulary. Write how people actually talk.\n"
        f"- Never boring. If it sounds like a Wikipedia summary, rewrite it as an argument.\n"
        f"- The CTA must feel natural, not like an ad break. It should come out of the conversation, not interrupt it."
    )

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            max_output_tokens=65536,
            thinking_config=types.ThinkingConfig(thinking_budget=0),
        ),
    )
    return (response.text or "").strip()
