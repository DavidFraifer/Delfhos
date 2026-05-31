"""
Speakable agent → ElevenLabs TTS (streaming)
============================================

A minimal example showing two Delfhos features working together:

  * ``comments="speakable"`` — the agent replies in natural spoken prose
    instead of Markdown, ready for text-to-speech.
  * ``agent.stream(...)`` — yields live snapshots as the agent works, so
    each spoken line is piped to ElevenLabs the moment it appears rather
    than waiting for the full answer.

The agent reads your Gmail inbox and summarises what's new — out loud.

Setup
-----
1. Install the ElevenLabs SDK:
       pip install elevenlabs

2. Install mpv (required by the SDK to play audio):
       macOS:          brew install mpv
       Linux (apt):    sudo apt install mpv
       Windows/other:  https://mpv.io/installation/

3. Add to your .env:
       GEMINI_API_KEY=...       # Google AI Studio — gemini.google.com
       ELEVENLABS_API_KEY=...   # ElevenLabs — elevenlabs.io/app/settings/api-keys

4. Place your Gmail OAuth client-secrets file at examples/oauth_gmail.json
   (Google Cloud Console → APIs & Services → Credentials → OAuth 2.0 Client).
   The first run opens a browser to authorise the account; after that it runs
   unattended.

Run:
    python examples/speakable_tts.py
"""

import os
from dotenv import load_dotenv

from delfhos import Agent
from delfhos.connections import GmailConnection
from elevenlabs.client import ElevenLabs
# NOTE: in elevenlabs>=2 `elevenlabs.play` is a submodule, not the function.
# `from elevenlabs import play` gives "object is not callable" — use this instead:
from elevenlabs.play import stream  # noqa: F401

load_dotenv()

# ── Voice ──────────────────────────────────────────────────────────────────────
# Requires a Creator plan or above (Voice Library voices are paywalled via API).
# Free-plan fallback: "ErXwobaYiN019PkySvjV"  (Antoni — speaks English well)
VOICE_ID = "eZCjPaC4W7mcOOERqE5n"
TTS_MODEL = "eleven_v3"
SPEED = 1.2  # 0.7 (slow) – 1.2 (fast), 1.0 = normal

# ── Agent personality ──────────────────────────────────────────────────────────
PERSONALITY = (
    "You are a helpful personal assistant reading emails out loud. "
    "Be concise and conversational — speak naturally as if talking to a friend, "
    "no bullet points, no markdown, no lists. Summarise what matters."
)

QUESTION = "Check my inbox and tell me if there's anything important or interesting today."

# OAuth client-secrets file, resolved next to this script (works from any CWD).
GMAIL_CREDENTIALS = os.path.join(os.path.dirname(__file__), "oauth_gmail.json")


def main() -> None:
    gmail = GmailConnection(
        oauth_credentials=GMAIL_CREDENTIALS,
        allow=["read"],   # read-only — the agent cannot send
        confirm=False,    # no approval prompt, so the voice flow isn't interrupted
    )

    agent = Agent(
        tools=[gmail],
        llm="gemini-3.1-flash-lite",
        system_prompt=PERSONALITY,
        comments="speakable",  # spoken prose instead of Markdown
        verbose=False,
    )

    tts = ElevenLabs(api_key=os.environ["ELEVENLABS_API_KEY"])

    def speak(text: str) -> None:
        audio = tts.text_to_speech.stream(
            text=text,
            voice_id=VOICE_ID,
            model_id=TTS_MODEL,
            output_format="mp3_44100_128",
            voice_settings={"speed": SPEED},
        )
        stream(audio)  # starts playing before synthesis finishes

    # Each `say` event is a line the agent spoke. Voice it as soon as it appears.
    spoken_so_far = 0
    for snap in agent.stream(QUESTION):
        says = [e for e in snap.events if e.kind == "say"]
        for ev in says[spoken_so_far:]:
            line = ev.label.strip()
            if line:
                print("🗣  ", line)
                speak(line)
        spoken_so_far = len(says)

    agent.stop()


if __name__ == "__main__":
    main()
