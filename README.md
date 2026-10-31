# mavis-ai
Voice and chat AI productivity assistant with persistent memory and workflow automation

## Run locally

Requires Python 3.10 or later.

    python -m venv .venv
    .venv\Scripts\Activate.ps1
    python -m pip install -r requirements.txt
    python app.py

Open http://localhost:5000. The task dashboard needs no model API key.
Tasks are stored in mavis.db; existing task databases are migrated automatically.

Create tasks with deadlines, importance, and estimated effort. Complete, reopen,
or delete tasks; switch between Open, Today (including overdue), and Completed.
Hear the next recommendation with browser speech synthesis.

Recommendations rank open tasks by the higher of importance and deadline urgency
(due today or overdue: critical; due within two days: high), then deadline,
then creation order. Estimates are shown for planning, but do not affect ranking.
Device-local dates define Today in the dashboard.

The original chat and transcription endpoints are retained. They require
MODEL_API_KEY in .env; transcription also requires ffmpeg on PATH.
The dashboard does not yet include chat or microphone controls.
This is a local single-user prototype; authentication is not implemented.

## Test

    python -m unittest discover -s tests -v

