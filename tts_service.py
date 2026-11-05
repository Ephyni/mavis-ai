
"""Local speech synthesis for MAVIS using Kokoro ONNX."""

import time
from functools import lru_cache
from pathlib import Path

from kokoro_onnx import Kokoro


MODEL_DIR = Path(__file__).parent / "models" / "kokoro"
VOICE = "am_puck"

# Cache only the short, fixed confirmations returned after verified actions.
# Never cache personal task names, memories, reminders, or model-generated text.
CACHED_CONFIRMATIONS = frozenset({
    "Task added and verified.",
    "Done. That task is completed and verified.",
    "Deleted and verified.",
    "Memory saved and verified.",
    "Memory deleted and verified.",
})


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


def _synthesize_speech(text):
    """Generate fresh samples without caching personalized content."""
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


@lru_cache(maxsize=len(CACHED_CONFIRMATIONS))
def _cached_confirmation_speech(text):
    """Hold synthesized samples for the limited fixed confirmation vocabulary."""
    return _synthesize_speech(text)


def generate_speech(text):
    """Return cached verified confirmations; synthesize all other text fresh."""
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Speech text must not be empty.")

    if text not in CACHED_CONFIRMATIONS:
        return _synthesize_speech(text)

    started = time.perf_counter()
    previous_hits = _cached_confirmation_speech.cache_info().hits
    audio = _cached_confirmation_speech(text)
    cache_hit = _cached_confirmation_speech.cache_info().hits > previous_hits
    print(
        f"MAVIS latency | Kokoro fixed reply cache "
        f"{'hit' if cache_hit else 'miss'}: "
        f"{(time.perf_counter() - started) * 1000:.0f} ms",
        flush=True,
    )
    return audio
