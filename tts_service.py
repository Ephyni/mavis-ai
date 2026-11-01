
"""Local speech synthesis for MAVIS using Kokoro ONNX."""

from functools import lru_cache
from pathlib import Path

from kokoro_onnx import Kokoro


MODEL_DIR = Path(__file__).parent / "models" / "kokoro"
VOICE = "am_puck"


@lru_cache(maxsize=1)
def get_tts_model():
    """Load the speech model once and reuse it across requests."""
    return Kokoro(
        str(MODEL_DIR / "kokoro-v1.0.onnx"),
        str(MODEL_DIR / "voices-v1.0.bin"),
    )


def generate_speech(text):
    """Convert MAVIS's response into audio samples."""
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Speech text must not be empty.")

    return get_tts_model().create(
        text,
        voice=VOICE,
        speed=1.05,
        lang="en-us",
    )
