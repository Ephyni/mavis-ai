
"""Compare three masculine Kokoro voices for MAVIS."""

from pathlib import Path

import soundfile as sf
from kokoro_onnx import Kokoro


def test_mavis_voices():
    """Generate separate samples for voice selection."""
    project_dir = Path(__file__).parent
    model_dir = project_dir / "models" / "kokoro"

    kokoro = Kokoro(
        str(model_dir / "kokoro-v1.0.onnx"),
        str(model_dir / "voices-v1.0.bin"),
    )

    voices = ["am_puck", "am_adam", "am_eric"]

    text = (
        "Hey there! I'm Mavis, your personal AI assistant. "
        "What are we working on today? "
        "I've got a few ideas, and I'd love to help!"
    )

    for voice in voices:
        print(f"Generating {voice}...")

        samples, sample_rate = kokoro.create(
            text,
            voice=voice,
            speed=1.05,
            lang="en-us",
        )

        output_path = project_dir / f"mavis_{voice}.wav"
        sf.write(output_path, samples, sample_rate)

        print(f"Saved: {output_path.name}")


if __name__ == "__main__":
    test_mavis_voices()