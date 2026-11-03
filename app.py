
import re
import json
from flask import Flask, jsonify, request, render_template, session
import os
from dotenv import load_dotenv
from openai import OpenAI
import subprocess
import tempfile
import requests

# Import MAVIS's SQLite task-management functions.
# The verified completion workflow separates task execution (Builder)
# from independent database verification (Verifier).
from memory import (
    get_tasks as get_saved_tasks,
    save_task,
    execute_verified_task_completion,
    delete_task as delete_saved_task,
    verify_task_deleted,
)

from memory import (
    init_db,
    save_memory,
    get_memories,
    propose_memory,
    get_proposals,
    approve_memory,
    reject_memory,
)

init_db()

app = Flask(__name__)

# Enable signed sessions for multi-step confirmation workflows.
load_dotenv()
app.config["SECRET_KEY"] = os.getenv("FLASK_SECRET_KEY")

if not app.config["SECRET_KEY"]:
    raise RuntimeError("FLASK_SECRET_KEY must be configured.")

import task_service
task_service.migrate()

@app.patch("/api/tasks/<int:task_id>")
def update_task(task_id):
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "A JSON object is required."}), 400
    try:
        if not task_service.update(task_id, data):
            return jsonify({"error": "Task not found."}), 404
        return jsonify({"status": "updated"})
    except ValueError as error:
        return jsonify({"error": str(error)}), 400

@app.delete("/api/tasks/<int:task_id>")
def delete_task(task_id):
    """Require explicit confirmation and verify permanent task deletion."""
    data = request.get_json(silent=True)

    # Reject deletion requests without an explicit confirmation.
    if not isinstance(data, dict) or data.get("confirm") is not True:
        return jsonify({
            "error": "Explicit confirmation is required before deleting a task."
        }), 400

    # Delete only the task identified by its database ID.
    if not delete_saved_task(task_id):
        return jsonify({"error": "Task not found."}), 404

    # Verify the persisted database state before reporting success.
    if not verify_task_deleted(task_id):
        return jsonify({
            "error": "Task deletion could not be verified."
        }), 500

    return jsonify({
        "status": "deleted",
        "task_id": task_id,
        "verified": True
    })

tasks = []

@app.get("/")
def home():
    """Render the MAVIS conversational interface."""
    return render_template("index.html")

@app.get("/api/tasks")
def get_tasks():
    try:
        from datetime import date
        today = date.fromisoformat(request.args["today"]) if "today" in request.args else None
        tasks = task_service.list_tasks(today)
        return jsonify({"tasks": tasks, "recommendation": task_service.recommendation(tasks)})
    except ValueError:
        return jsonify({"error": "Invalid date."}), 400

@app.post("/api/tasks")
def create_task():
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify({"error": "A JSON object is required."}), 400
    try:
        task_id = task_service.create(data)
        return jsonify({"id": task_id}), 201
    except ValueError as error:
        return jsonify({"error": str(error)}), 400


@app.post("/api/memories")
def create_memory():
    data = request.get_json(silent=True) or {}
    content = data.get("content")

    if not isinstance(content, str) or not content.strip():
        return jsonify({"error": "Content is required"}), 400

    memory_id = save_memory(content.strip())

    return jsonify({
        "id": memory_id,
        "message": "Memory saved successfully!"
    }), 201


@app.get("/api/memories")
def list_memories():
    return jsonify({
        "memories": get_memories()
    })

@app.post("/api/memory-proposals")
def create_memory_proposal():
    data = request.get_json(silent=True) or {}
    content = data.get("content")
    category = data.get("category", "general")

    if not isinstance(content, str) or not content.strip():
        return jsonify({"error": "Content is required"}), 400

    if not isinstance(category, str) or not category.strip():
        return jsonify({"error": "Category is required"}), 400

    proposal_id = propose_memory(content.strip(), category.strip())

    return jsonify({
        "id": proposal_id,
        "status": "pending"
    }), 201


@app.get("/api/memory-proposals")
def list_memory_proposals():
    return jsonify({"proposals": get_proposals()})


@app.post("/api/memory-proposals/<int:proposal_id>/approve")
def approve_memory_proposal(proposal_id):
    memory_id = approve_memory(proposal_id)

    if memory_id is None:
        return jsonify({"error": "Pending proposal not found"}), 404

    return jsonify({
        "memory_id": memory_id,
        "status": "approved"
    })


@app.post("/api/memory-proposals/<int:proposal_id>/reject")
def reject_memory_proposal(proposal_id):
    rejected = reject_memory(proposal_id)

    if not rejected:
        return jsonify({"error": "Pending proposal not found"}), 404

    return jsonify({"status": "rejected"})


@app.post("/api/chat")
def chat(message_override=None):
    # Allow voice and text commands to share the current request session.
    data = request.get_json(silent=True) or {}

    if message_override is not None:
        data = {"message": message_override}

    message = data.get("message")


    if not isinstance(message, str) or not message.strip():
        return jsonify({"error": "Message is required"}), 400


    # Resolve a pending deletion before classifying a new AI intent.
    pending_task_id = session.get("pending_delete_task_id")

    if pending_task_id is not None:
        answer = message.strip().casefold().rstrip(".!?")

        cancel_answers = {
            "no", "no cancel", "no, cancel",
            "cancel", "cancel deletion",
            "don't delete it", "do not delete it"
        }

        confirm_answers = {
            "yes", "yes delete it", "yes, delete it",
            "confirm deletion", "confirm delete",
            "yes please delete it", "yes, please delete it"
        }

        if answer in cancel_answers:
            session.pop("pending_delete_task_id", None)

            return jsonify({
                "reply": "Okay, deletion cancelled. Your task is safe.",
                "intent": "delete_task",
                "cancelled": True
            })

        if answer in confirm_answers:
            # Consume the confirmation so it cannot be reused.
            session.pop("pending_delete_task_id", None)

            if type(pending_task_id) is not int or pending_task_id <= 0:
                return jsonify({"error": "Invalid pending task."}), 400

            selected_task = next(
                (
                    task for task in get_saved_tasks()
                    if task["id"] == pending_task_id
                ),
                None
            )

            if selected_task is None:
                return jsonify({
                    "reply": "That task no longer exists.",
                    "intent": "delete_task"
                }), 404

            # Delete the selected record and verify its persisted state.
            deleted = delete_saved_task(pending_task_id)
            verified = verify_task_deleted(pending_task_id) if deleted else False

            if not (deleted and verified):
                return jsonify({
                    "reply": "I couldn't verify the deletion.",
                    "intent": "delete_task",
                    "verified": False
                }), 500

            return jsonify({
                "reply": (
                    f"Permanently deleted '{selected_task['title']}' "
                    "and verified its removal."
                ),
                "intent": "delete_task",
                "task_id": pending_task_id,
                "verified": True
            })

        # An unrelated command cancels the pending confirmation.
        session.pop("pending_delete_task_id", None)


    if message.lower().startswith("add task:"):
        title = message.split(":", 1)[1].strip()

        if not title:
            return jsonify({"error": "Task title is required"}), 400

        task_id = save_task(title)

        return jsonify({
            "reply": f"I've added '{title}' to your task list.",
            "task_id": task_id
        })

    load_dotenv()

    client = OpenAI(
        base_url="https://api.meta.ai/v1",
        api_key=os.environ["MODEL_API_KEY"]
    )


    intent_instructions = (
        "Classify the user's message as one of these intents: "
        "'add_task', 'list_tasks', 'complete_task', 'delete_task', "
        "'reminder', or 'chat'. "
        "Use 'list_tasks' when the user asks to see or hear their tasks. "
        "Use 'delete_task' when the user asks to delete or remove a task. "
        "Do not perform any actions. "
        "Reply with only the classification."
    )


    intent_response = client.responses.create(
        model="muse-spark-1.3",
        instructions=intent_instructions,
        input=message.strip()
    )

    intent = intent_response.output_text.strip().lower()

    # Route explicit task-list requests deterministically.
    normalized_message = message.casefold()

    if "tasks" in normalized_message and any(
        phrase in normalized_message
        for phrase in ("show", "list", "see", "what are", "read")
    ):
        intent = "list_tasks"

    # Log the classified intent to diagnose voice-command routing.
    print("MAVIS intent:", repr(intent))

    if intent not in {
        "add_task",
        "list_tasks",
        "complete_task",
        "delete_task",
        "reminder",
        "chat",
    }:
        intent = "chat"

    if intent == "add_task":
        title_response = client.responses.create(
            model="muse-spark-1.3",
            instructions=(
                "Extract the task title from the user's message. "
                "Return only the task title, without extra words."
            ),
            input=message.strip()
        )

        title = title_response.output_text.strip()
        task_id = save_task(title)

        return jsonify({
            "reply": f"I've added '{title}' to your task list.",
            "task_id": task_id,
            "intent": intent
       })

    if intent == "list_tasks":
        saved_tasks = get_saved_tasks()

        print("DEBUG list_tasks count:", len(saved_tasks), flush=True)

        # Filter tasks according to the requested completion status.
        normalized_message = message.casefold()

        if "completed" in normalized_message or "finished" in normalized_message:
            saved_tasks = [
                task for task in saved_tasks
                if task["completed"] == 1
            ]
        elif any(
            word in normalized_message
            for word in ("active", "open", "incomplete", "pending")
        ):
            saved_tasks = [
                task for task in saved_tasks
                if task["completed"] == 0
            ]

        if not saved_tasks:
            return jsonify({
                "reply": "You don't have any saved tasks yet.",
                "intent": intent,
                "tasks": []
            })


        task_titles = [task["title"] for task in saved_tasks]

        # Confirm which tasks are included in the API response.
        print("DEBUG returning task titles:", task_titles, flush=True)

        return jsonify({
            "reply": "Here are your tasks: " + ", ".join(task_titles),
            "intent": intent,
            "tasks": saved_tasks
        })


    if intent == "delete_task":
        # Identify the target before requesting permanent deletion.
        saved_tasks = get_saved_tasks()
        normalized_message = message.casefold()

        matches = [
            task for task in saved_tasks
            if task["title"].strip().casefold() in normalized_message
        ]

        # Never proceed when the task is missing or ambiguous.
        if len(matches) != 1:
            return jsonify({
                "reply": (
                    "I couldn't identify exactly one task. "
                    "Please tell me the exact task name."
                ),
                "intent": intent,
                "confirmation_required": False
            })

        selected_task = matches[0]

        # Remember the selected task until the user confirms or cancels.
        session["pending_delete_task_id"] = selected_task["id"]


        # Ask for confirmation without modifying SQLite.
        return jsonify({
            "reply": (
                f"Are you sure you want to permanently delete "
                f"'{selected_task['title']}'? This cannot be undone."
            ),
            "intent": intent,
            "confirmation_required": True,
            "task_id": selected_task["id"]
        })

    if intent == "complete_task":
        # Retrieve persisted tasks before selecting a completion target.
        saved_tasks = get_saved_tasks()
               # Resolve an explicitly named task without bypassing ID validation.
        task_id = data.get("task_id")

        # Resolve a spoken task ID before task-name matching.
        if task_id is None:
            match = re.search(
                r"\btask\s*(?:number\s*|#\s*)?(\d+)\b",
                message,
                re.IGNORECASE,
            )
            if match:
                task_id = int(match.group(1))

        if task_id is None:
            matches = [
                task for task in saved_tasks
                if task["completed"] == 0
                and task["title"].strip().casefold()
                in message.strip().casefold()
            ]

            if len(matches) == 1:
                task_id = matches[0]["id"]

        if task_id is not None:
            if type(task_id) is not int or task_id <= 0:
                return jsonify({
                    "error": "A positive integer task ID is required."
                }), 400

            # Only permit completion of an existing, incomplete task.
            selected_task = next(
                (
                    task for task in saved_tasks
                    if task["id"] == task_id
                    and task["completed"] == 0
                ),
                None
            )

            if selected_task is None:
                return jsonify({
                    "error": "Task not found or already completed."
                }), 404

            result = execute_verified_task_completion(task_id)

            return jsonify({
                "reply": (
                    f"Completed '{selected_task['title']}' and verified it."
                    if result["status"] == "verified"
                    else "Task completion could not be verified."
                ),
                "intent": intent,
                "task_id": task_id,
                "verification": result
            })

        incomplete_tasks = [
            task for task in saved_tasks
            if task["completed"] == 0
        ]

        if not incomplete_tasks:
            return jsonify({
                "reply": "You don't have any incomplete tasks.",
                "intent": intent
            })

        # Require an explicit task selection before changing SQLite.
        return jsonify({
            "reply": "Which task would you like me to complete?",
            "intent": intent,
            "tasks": incomplete_tasks
        })

    response = client.responses.create(
        model="muse-spark-1.3",
        instructions=(
            "You are MAVIS, a friendly, energetic, and curious AI personal assistant. "
            "Speak naturally, with warmth, confidence, and a positive attitude. "
            "Be conversational, approachable, and professional without sounding robotic. "
            "Use proper grammar, punctuation, and natural sentence structure. "
            "Write responses that sound clear and conversational when spoken aloud. "
            "Use short, natural sentences and avoid awkward phrasing. "
            "Keep responses concise, especially for voice interactions. "
            "Avoid Markdown formatting, unnecessary symbols, and long lists. "
            "Use a friendly, upbeat tone without excessive enthusiasm. "
            "Help users organize tasks, plan their day, and stay productive. "
            "Offer helpful next steps when relevant, without being pushy. "
            "Preserve important details, including task names, dates, and times. "
            "Never invent information or claim an action was successful without verification. "
            "Never claim to have created reminders, sent emails, updated calendars, "
            "or completed tasks unless those actions have actually been "
            "completed and verified."
        ),
        input=message.strip(),
    )

    return jsonify({"reply": response.output_text})



def convert_audio_to_wav(input_path, output_path):
    """Convert browser audio to mono 24 kHz PCM WAV for transcription."""
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i", input_path,
            "-ac", "1",
            "-ar", "24000",
            "-c:a", "pcm_s16le",
            output_path,
        ],
        check=True,
        capture_output=True,
        timeout=30,
    )


def transcribe_audio(wav_path):
    """Transcribe WAV audio using Meta's Muse Voice Transcribe API."""
    load_dotenv()

    api_key = os.environ["MODEL_API_KEY"]

    with open(wav_path, "rb") as audio_file:
        response = requests.post(
            "https://api.meta.ai/v1/asr/transcribe",
            headers={
                "Authorization": f"Bearer {api_key}"
            },
            
            data={
                "request": json.dumps({
                    "model": "muse-voice-transcribe-1.0",
                    "mode": "PUSH_TO_TALK",
                    "audioEncoding": "WAV",
                })
            },

            files={
                "audio": ("recording.wav", audio_file, "audio/wav")
            },
            timeout=60,
        )

    if not response.ok:
        print("Meta transcription error:", response.status_code)
        
    response.raise_for_status()
    return response.json()



@app.post("/api/voice")
def receive_voice():
    """Validate an uploaded voice recording before transcription."""
    audio = request.files.get("audio")

    if audio is None or not audio.filename:
        return jsonify({
            "error": "An audio recording is required."
        }), 400

    
    try:
        # Isolate uploaded and converted audio in temporary files.
        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = os.path.join(temp_dir, "recording.webm")
            output_path = os.path.join(temp_dir, "recording.wav")

            audio.save(input_path)
            convert_audio_to_wav(input_path, output_path)

            # Return only the transcript after Meta confirms success.
            result = transcribe_audio(output_path)
            transcript = result.get("transcript", "").strip()

            print("MAVIS transcript:", repr(transcript))
            
            if not transcript:
                return jsonify({
                    "error": "No speech was recognized."
                }), 422


            # Process the spoken command within the original browser session.
            return chat(transcript)


    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return jsonify({
            "error": "Audio conversion failed."
        }), 422

    except requests.RequestException:
        return jsonify({
            "error": "Voice transcription service unavailable."
        }), 502



@app.post("/api/tts")
def text_to_speech():
    """Generate a WAV response using MAVIS's selected voice."""
    from io import BytesIO

    import soundfile as sf
    from flask import jsonify, request, send_file

    from tts_service import generate_speech

    data = request.get_json(silent=True) or {}
    text = data.get("text")

    if not isinstance(text, str) or not 0 < len(text.strip()) <= 300:
        return jsonify({"error": "Text must contain 1–300 characters."}), 400

    samples, sample_rate = generate_speech(text)

    audio_buffer = BytesIO()
    sf.write(audio_buffer, samples, sample_rate, format="WAV")
    audio_buffer.seek(0)

    return send_file(
        audio_buffer,
        mimetype="audio/wav",
        download_name="mavis_response.wav",
    )

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
