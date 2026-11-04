
"""Local speech synthesis for MAVIS using Kokoro ONNX."""

import time
from functools import lru_cache
from pathlib import Path

from kokoro_onnx import Kokoro


MODEL_DIR = Path(__file__).parent / "models" / "kokoro"
VOICE = "am_michael"


@lru_cache(maxsize=1)
def get_tts_model():
    """Load the speech model once and reuse it across requests."""
    started = time.perf_counter()
    model = Kokoro(
        str(MODEL_DIR / "kokoro-v1.0.onnx"),
        str(MODEL_DIR / "voices-v1.0.bin"),
    )
    print(
        f"MAVIS latency | Kokoro first load: "
        f"{(time.perf_counter() - started) * 1000:.0f} ms",
        flush=True,
    )
    return model



def preload_tts_model():
    """Warm Kokoro once at startup without disabling other app features on failure."""
    started = time.perf_counter()
    try:
        get_tts_model()
    except Exception as error:
        # Keep task, memory, and chat endpoints available if speech cannot load.
        print(
            f"MAVIS TTS preload unavailable ({type(error).__name__}); "
            "speech will retry when requested.",
            flush=True,
        )
        return False

    print(
        f"MAVIS latency | Kokoro preload ready: "
        f"{(time.perf_counter() - started) * 1000:.0f} ms",
        flush=True,
    )
    return True


def generate_speech(text):
    """Generate natural, conversational speech for MAVIS."""
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Speech text must not be empty.")

    started = time.perf_counter()
    samples, sample_rate = get_tts_model().create(
        text,
        voice=VOICE,
        speed=1.15,
        lang="en-us",
    )
    print(
        f"MAVIS latency | Kokoro generation (includes first load): "
        f"{(time.perf_counter() - started) * 1000:.0f} ms",
        flush=True,
    )
    return samples, sample_rate
