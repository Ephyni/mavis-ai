
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
    verify_task_created,
    execute_verified_task_completion,
    delete_task as delete_saved_task,
    verify_task_deleted,
)

from memory import (
    init_db,
    save_memory,
    get_memories,
    delete_memory,
    verify_memory_deleted,
    propose_memory,
    get_proposals,
    approve_memory,
    reject_memory,
    save_reminder,
    verify_reminder_saved,
    get_reminders,
    get_task_activity,
    get_due_reminders,
    mark_reminder_notified,
)

from reminder_speech import format_spoken_reminder
from memory_commands import extract_memory_fact, makes_unverified_memory_claim
from action_flow import clear_pending, confirmation_answer

init_db()

app = Flask(__name__)

# Enable signed sessions for multi-step confirmation workflows.
load_dotenv()
app.config["SECRET_KEY"] = os.getenv("FLASK_SECRET_KEY")

if not app.config["SECRET_KEY"]:
    raise RuntimeError("FLASK_SECRET_KEY must be configured.")

import task_service
task_service.migrate()


# Route explicit task commands deterministically while retaining Muse Spark
# for less structured requests. These helpers never mutate the database.
def _explicit_task_intent(message):
    command = " ".join(message.casefold().strip().split())
    command = re.sub(r"^(?:hey|hi|okay|ok)[,\s]+", "", command)
    command = re.sub(r"^mavis[,\s]+", "", command)
    command = re.sub(
        r"^(?:(?:please|can you|could you|would you|will you|"
        r"i want you to|i need you to|i want to|i need to)\s+)+",
        "", command,
    )

    if re.match(r"^(?:how|why|when|where|don't|do not|never)\b", command):
        return None
    if re.search(r"\b(?:remind me|set a reminder)\b", command):
        return None

    if (
        re.match(r"^(?:list|show|read|tell me|give me|what are|what's|which are)\b", command)
        and re.search(r"\b(?:tasks?|to[- ]?dos?)\b", command)
    ):
        return "list_tasks"
    if re.match(r"^(?:delete|remove|erase)\b", command):
        return "delete_task"
    if re.match(r"^(?:complete|finish|check off|tick off)\b", command):
        return "complete_task"
    if (
        re.match(r"^(?:mark|set)\b", command)
        and re.search(r"\b(?:done|complete|completed|finished)\b", command)
    ):
        return "complete_task"
    if re.match(r"^i(?:'ve| have)?\s+(?:completed|finished)\b", command):
        return "complete_task"

    return None


_TASK_COMMAND_WORDS = {
    "mavis", "hey", "hi", "please", "can", "could", "would", "will",
    "you", "i", "ve", "have", "want", "need", "me", "my", "your",
    "the", "a", "an", "this", "that", "task", "tasks", "number", "id",
    "named", "called", "is", "to", "for", "of", "at", "on", "in",
    "as", "from", "and", "with", "list", "done", "mark", "set",
    "complete", "completed", "finish", "finished", "check", "tick",
    "off", "delete", "remove", "erase", "permanently",
}
_TASK_TITLE_FILLERS = {
    "the", "a", "an", "my", "your", "to", "for", "of", "at", "on", "in", "and"
}


def _task_words(text):
    return re.findall(r"[^\W_]+", text.casefold(), flags=re.UNICODE)


def _task_matches(message, available_tasks):
    """Choose a uniquely named task; return candidates when uncertain."""
    number = re.search(r"\btask\s*(?:number\s*|id\s*|#\s*)?(\d+)\b", message, re.I)
    if number:
        found = next((task for task in available_tasks
                      if task["id"] == int(number.group(1))), None)
        return found, [found] if found else []

    query = [word for word in _task_words(message)
             if word not in _TASK_COMMAND_WORDS]
    if not query:
        return None, []

    # Matching an exact name outranks every overlapping, longer name.
    exact = [task for task in available_tasks
             if [word for word in _task_words(task["title"])
                 if word not in _TASK_TITLE_FILLERS] == query]
    if exact:
        exact.sort(key=lambda task: task["id"], reverse=True)
        return (exact[0] if len(exact) == 1 else None), exact

    keywords = set(query)
    candidates = []
    for task in available_tasks:
        words = set(_task_words(task["title"])) - _TASK_TITLE_FILLERS
        common = len(keywords & words)
        if (len(keywords) == 1 and common == 1) or (
            len(keywords) > 1 and common >= 2
            and common / len(keywords) >= 0.65
        ):
            candidates.append(task)
    candidates.sort(key=lambda task: task["id"], reverse=True)
    return (candidates[0] if len(candidates) == 1 else None), candidates


def _task_choice_from_reply(message, options):
    """Use a spoken position or creation order only for pending choices."""
    if len(options) < 2:
        return None
    words = _task_words(message)
    words = [word for word in words if word not in {
        "the", "one", "task", "mavis", "please", "i", "mean",
        "meant", "choose", "select", "option",
    }]
    phrase = " ".join(words)
    ordinals = {
        "first": 0, "1st": 0, "second": 1, "2nd": 1,
        "third": 2, "3rd": 2, "fourth": 3, "4th": 3,
        "number one": 0, "number two": 1, "number three": 2,
        "number four": 3,
    }
    if phrase in ordinals:
        index = ordinals[phrase]
        return options[index] if index < len(options) else None
    duplicate_names = len({
        tuple(_task_words(task["title"])) for task in options
    }) == 1
    if duplicate_names and phrase in {"newer", "newest", "latest"}:
        return max(options, key=lambda task: task["id"])
    if duplicate_names and phrase in {"older", "oldest"}:
        return min(options, key=lambda task: task["id"])
    return None


def _task_selection_reply(action, matches):
    """Ask for a task name, not an internal SQLite identifier."""
    if not matches:
        return f"Which task would you like me to {action}? Please say its name."
    names = {}
    for task in matches:
        key = tuple(_task_words(task["title"]))
        names.setdefault(key, []).append(task)
    if len(names) == 1:
        group = next(iter(names.values()))
        title = group[0]["title"]
        if len(group) == 2:
            return (f"I found two tasks named '{title}'. "
                    "Would you like the newer one or the older one?")
        return (f"I found {len(group)} tasks named '{title}'. "
                "Please say newest, oldest, or the first, second, third "
                "or fourth one, counting from newest to oldest.")
    choices = [
        f"'{group[0]['title']}'" +
        (f" ({len(group)} copies)" if len(group) > 1 else "")
        for group in list(names.values())[:4]
    ]
    return ("I found several possible tasks: " + ", or ".join(choices) +
            ". Which task name did you mean? You can say just its name.")


# Interpret only explicit memory-forgetting instructions, not task deletion.
def _memory_deletion_subject(message):
    command = message.strip().casefold()
    command = re.sub(r"^(?:(?:hey|hi)[,\s]+)?mavis[,\s]+", "", command)
    command = re.sub(
        r"^(?:(?:please|can you|could you|would you)\s+)+",
        "", command,
    )
    if re.match(r"^(?:don't|do not|never)\b", command):
        return None
    if re.match(r"^forget\b", command):
        subject = re.sub(r"^forget\b", "", command, count=1).strip()
    else:
        match = re.match(
            r"^(?:delete|remove|erase)\s+"
            r"(?:(?:the|my|a)\s+)?(?:(?:saved|stored)\s+)?"
            r"memories?\b(.*)$",
            command,
        )
        if match is None:
            return None
        subject = match.group(1).strip()
    subject = re.sub(
        r"^(?:(?:that|about|of|saying|which says|the fact that|"
        r"what i told you about)\s+)+", "", subject,
    )
    return subject.strip(" .,!?")


_MEMORY_FILLERS = {
    "i", "am", "my", "your", "the", "a", "an", "that", "is", "was",
    "are", "to", "for", "of", "on", "at", "about", "in", "me",
    "memory", "saved", "remember", "it",
}


def _saved_memory_matches(subject, available):
    """Require a unique exact or keyword match; never guess between memories."""
    query = [
        word for word in _task_words(subject) if word not in _MEMORY_FILLERS
    ]
    if not query:
        return None, []
    exact = [
        item for item in available
        if [word for word in _task_words(item["content"])
            if word not in _MEMORY_FILLERS] == query
    ]
    if exact:
        return (exact[0] if len(exact) == 1 else None), exact
    wanted = set(query)
    candidates = [
        item for item in available
        if wanted.issubset(
            set(_task_words(item["content"])) - _MEMORY_FILLERS
        )
    ]
    if not candidates and len(wanted) >= 2:
        # Small transcript differences are allowed only for one unique match.
        for item in available:
            tokens = set(_task_words(item["content"])) - _MEMORY_FILLERS
            overlap = len(wanted & tokens)
            if overlap >= 2 and overlap / len(wanted) >= 0.7:
                candidates.append(item)
    return (candidates[0] if len(candidates) == 1 else None), candidates


def _memory_delete_question(matches):
    """Ask for an identifiable memory before requesting confirmation."""
    if not matches:
        return (
            "I couldn't identify that saved memory. "
            "Please say what it says or use Delete on the Memory screen."
        )
    if len(matches) == 1:
        return f"Are you sure you want me to forget: '{matches[0]['content']}'?"
    choices = "; ".join(
        f"{index}. {item['content'][:100]}"
        for index, item in enumerate(matches[:4], start=1)
    )
    return (
        "I found more than one matching memory: " + choices +
        ". Please say which one, such as first or second, or its name."
    )


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

@app.get("/api/task-activity")
def recent_task_activity():
    """Expose real task actions in persisted newest-first order."""
    return jsonify({"events": get_task_activity(limit=2)})


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


@app.post("/api/reminders")
def create_reminder():
    """Create a reminder and verify its persisted database state."""
    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return jsonify({"error": "A JSON object is required."}), 400

    message = data.get("message")
    due_at = data.get("due_at")

    try:
        # Builder: persist the requested reminder.
        reminder_id = save_reminder(message, due_at)
    except ValueError as error:
        return jsonify({"error": str(error)}), 400

    # Verifier: independently confirm the saved message and due time.
    verified = verify_reminder_saved(reminder_id, message, due_at)

    if not verified:
        return jsonify({
            "error": "Reminder creation could not be verified.",
            "verified": False
        }), 500

    return jsonify({
        "id": reminder_id,
        "status": "created",
        "verified": True
    }), 201


@app.get("/api/reminders/due")
def due_reminders():
    """Return pending reminders whose scheduled time has arrived."""
    reminders = get_due_reminders()

    return jsonify({
        "reminders": reminders,
        "count": len(reminders)
    })

@app.post("/api/reminders/<int:reminder_id>/acknowledge")
def acknowledge_reminder(reminder_id):
    """Record acknowledgment of an eligible due reminder."""
    acknowledged = mark_reminder_notified(reminder_id)

    return jsonify({
        "reminder_id": reminder_id,
        "acknowledged": acknowledged
    }), 200 if acknowledged else 409


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


@app.delete("/api/memories/<int:memory_id>")
def remove_saved_memory(memory_id):
    """Delete one confirmed saved memory, then independently verify removal."""
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or data.get("confirm") is not True:
        return jsonify({"error": "Confirm before deleting a saved memory."}), 400
    deleted = delete_memory(memory_id)
    if not deleted:
        return jsonify({"error": "Saved memory not found."}), 404
    if not verify_memory_deleted(memory_id):
        return jsonify({
            "error": "Memory deletion could not be verified.", "verified": False
        }), 500
    return jsonify({
        "status": "deleted", "memory_id": memory_id, "verified": True
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


    # A new explicit command replaces, rather than inherits, an older action.
    new_action = (
        _memory_deletion_subject(message) is not None
        or extract_memory_fact(message) is not None
        or _explicit_task_intent(message) is not None
        or message.strip().casefold().startswith((
            "add task:", "mavis add", "mavis, add",
            "remind me", "mavis remind me", "mavis, remind me",
            "set a reminder",
        ))
    )
    if new_action:
        old_proposal = session.get("pending_memory_proposal_id")
        if type(old_proposal) is int:
            reject_memory(old_proposal)
        clear_pending(session)

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

        if answer in cancel_answers or confirmation_answer(message) == "no":
            session.pop("pending_delete_task_id", None)

            return jsonify({
                "reply": "Okay, deletion cancelled. Your task is safe.",
                "intent": "delete_task",
                "cancelled": True
            })

        if answer in confirm_answers or confirmation_answer(message) == "yes":
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

        return jsonify({
            "reply": "Please confirm that task deletion with yes or no.",
            "intent": "delete_task",
            "confirmation_required": True,
        })


    # Handle voice and text deletion of already-approved memories before
    # the save-memory workflow or Muse intent classification.
    memory_answer = message.strip().casefold().strip(" .!?")
    pending_delete_memory = session.get("pending_delete_memory_id")
    accept_delete = {
        "yes", "yes please", "yes, please", "yes delete it",
        "yes, delete it", "yes forget it", "yes, forget it",
        "confirm", "confirm deletion", "delete it", "forget it",
    }
    reject_delete = {
        "no", "no thanks", "no, thanks", "cancel", "never mind",
        "nevermind", "don't delete it", "do not delete it",
    }
    if pending_delete_memory is not None:
        if memory_answer in accept_delete or confirmation_answer(message) == "yes":
            session.pop("pending_delete_memory_id", None)
            if type(pending_delete_memory) is not int:
                return jsonify({"error": "Invalid saved-memory selection."}), 400
            removed = delete_memory(pending_delete_memory)
            verified = verify_memory_deleted(pending_delete_memory) if removed else False
            if not verified:
                return jsonify({
                    "reply": "I couldn't verify that memory's deletion.",
                    "intent": "delete_memory", "verified": False,
                }), 409
            return jsonify({
                "reply": "I've forgotten that memory and verified its removal.",
                "intent": "delete_memory",
                "memory_id": pending_delete_memory,
                "verified": True,
            })
        if memory_answer in reject_delete or confirmation_answer(message) == "no":
            session.pop("pending_delete_memory_id", None)
            return jsonify({
                "reply": "Okay, I kept that memory.",
                "intent": "delete_memory", "cancelled": True,
            })

        return jsonify({
            "reply": "Please confirm that memory deletion with yes or no.",
            "intent": "delete_memory",
            "confirmation_required": True,
        })

    # A follow-up can select one of the saved memories MAVIS just offered.
    pending_options = session.get("pending_memory_delete_options", [])
    if session.get("pending_memory_selection") or pending_options:
        if memory_answer in reject_delete or confirmation_answer(message) == "no":
            session.pop("pending_memory_selection", None)
            session.pop("pending_memory_delete_options", None)
            return jsonify({
                "reply": "Okay, I kept those memories.",
                "intent": "delete_memory", "cancelled": True,
            })
        stored_memories = get_memories()
        choices = (
            [next((item for item in stored_memories if item["id"] == option), None)
             for option in pending_options[:4]]
            if pending_options else stored_memories
        )
        choices = [item for item in choices if item is not None]
        if confirmation_answer(message) == "yes":
            return jsonify({
                "reply": "Please identify the saved memory by name.",
                "intent": "delete_memory",
                "confirmation_required": False,
            })
        order = {
            "first": 0, "the first one": 0,
            "second": 1, "the second one": 1,
            "third": 2, "the third one": 2,
            "fourth": 3, "the fourth one": 3,
            "newest": 0, "the newer one": 0,
            "oldest": -1, "the older one": -1,
        }
        index = order.get(memory_answer)
        selected = None
        if index is not None and -len(choices) <= index < len(choices):
            selected = choices[index]
        if selected is None and choices and index is None:
            selected, matches = _saved_memory_matches(message, choices)
            if selected is None and matches:
                choices = matches
        if selected is not None:
            session.pop("pending_memory_selection", None)
            session.pop("pending_memory_delete_options", None)
            session["pending_delete_memory_id"] = selected["id"]
            return jsonify({
                "reply": _memory_delete_question([selected]),
                "intent": "delete_memory", "confirmation_required": True,
            })
        session["pending_memory_selection"] = True
        session["pending_memory_delete_options"] = (
            [item["id"] for item in choices[:4]] if pending_options else []
        )
        return jsonify({
            "reply": _memory_delete_question(choices if pending_options else []),
            "intent": "delete_memory", "confirmation_required": False,
        })

    forget_subject = _memory_deletion_subject(message)
    if forget_subject is not None:
        session.pop("pending_task_selection", None)
        session.pop("pending_task_options", None)
        if not forget_subject:
            session["pending_memory_selection"] = True
            return jsonify({
                "reply": (
                    "Which saved memory should I forget? "
                    "Tell me what it says or use the Memory screen."
                ),
                "intent": "delete_memory",
            })
        selected, matches = _saved_memory_matches(
            forget_subject, get_memories()
        )
        if selected is None:
            session["pending_memory_selection"] = True
            session["pending_memory_delete_options"] = [
                item["id"] for item in matches[:4]
            ]
            return jsonify({
                "reply": _memory_delete_question(matches),
                "intent": "delete_memory", "confirmation_required": False,
            })
        session["pending_delete_memory_id"] = selected["id"]
        return jsonify({
            "reply": _memory_delete_question([selected]),
            "intent": "delete_memory", "confirmation_required": True,
        })

    # Handle explicit conversational memory requests before model intent routing.
    # Voice and text use this same handler and require approval before saving.
    memory_answer = message.strip().casefold().rstrip(".!?").strip()
    memory_fact = extract_memory_fact(message)
    pending_memory_id = session.get("pending_memory_proposal_id")

    if pending_memory_id is not None:
        accept_memory = {
            "yes", "yes please", "yes, please", "yes save it",
            "yes, save it", "yes please save it", "save it",
            "please save it", "confirm", "confirm save",
            "sure", "go ahead",
        }
        decline_memory = {
            "no", "no thanks", "no, thanks", "cancel",
            "don't save it", "do not save it",
            "no, don't save it", "no don't save it", "reject",
        }

        if memory_answer in accept_memory or confirmation_answer(message) == "yes":
            # Consume this confirmation once to prevent a repeated "yes" saving twice.
            session.pop("pending_memory_proposal_id", None)
            proposal = next(
                (item for item in get_proposals()
                 if item["id"] == pending_memory_id),
                None,
            )
            if proposal is None:
                return jsonify({
                    "reply": "That memory is no longer pending approval.",
                    "intent": "save_memory",
                    "verified": False,
                }), 409

            memory_id = approve_memory(pending_memory_id)
            saved = next(
                (item for item in get_memories()
                 if item["id"] == memory_id
                 and item["content"] == proposal["content"]),
                None,
            )
            if saved is None:
                return jsonify({
                    "reply": "I couldn't verify that the memory was saved.",
                    "intent": "save_memory",
                    "verified": False,
                }), 500

            return jsonify({
                "reply": f"Saved and verified. I'll remember: {saved['content']}",
                "intent": "save_memory",
                "memory_id": memory_id,
                "verified": True,
            })

        # Keep an unrecognized reply pending until yes, no, or a new action.
        if memory_answer in decline_memory or confirmation_answer(message) == "no":
            session.pop("pending_memory_proposal_id", None)
            rejected = reject_memory(pending_memory_id)
            return jsonify({
                "reply": (
                    "Okay, I won't save that memory."
                    if rejected else "That memory is no longer pending approval."
                ),
                "intent": "save_memory",
                "cancelled": rejected,
            })

        return jsonify({
            "reply": "Would you like me to save that memory? Please say yes or no.",
            "intent": "save_memory",
            "pending_approval": True,
        })

    if memory_fact is not None:
        fact = memory_fact
        if not fact:
            return jsonify({
                "reply": "What would you like me to remember?",
                "intent": "save_memory",
            })
        if len(fact) > 500:
            return jsonify({
                "reply": "Please keep that memory under 500 characters.",
                "intent": "save_memory",
            }), 400

        proposal_id = propose_memory(fact)
        proposed = next(
            (item for item in get_proposals()
             if item["id"] == proposal_id and item["content"] == fact),
            None,
        )
        if proposed is None:
            return jsonify({
                "reply": "I couldn't verify the memory request.",
                "intent": "save_memory",
                "verified": False,
            }), 500

        session["pending_memory_proposal_id"] = proposal_id
        return jsonify({
            "reply": (
                f"I can remember that: {fact} "
                "Would you like me to save it? Say yes or no."
            ),
            "intent": "save_memory",
            "proposal_id": proposal_id,
            "pending_approval": True,
        })

    # Remember requests that need a task name. A subsequent title or task
    # number can resolve the action without requiring the verb again.
    pending_selection = session.get("pending_task_selection")
    option_ids = session.get("pending_task_options", [])
    follow_up_task_intent = None
    follow_up_task_id = None
    if pending_selection in {"complete_task", "delete_task"}:
        answer = message.strip().casefold().rstrip(".!?").strip()
        if answer in {"no", "cancel", "never mind", "nevermind", "stop"}:
            return jsonify({
                "reply": "Okay, I cancelled that task request.",
                "intent": pending_selection,
                "cancelled": True,
            })

        new_command = _explicit_task_intent(message)
        unrelated = re.match(
            r"^(?:(?:mavis[,\s]+)?(?:please\s+)?)"
            r"(?:remind|remember|add|create|list|show|what|why|when|how|where)\b",
            answer,
        )
        if new_command is None and unrelated is None:
            follow_up_task_intent = pending_selection
            current = get_saved_tasks()
            if pending_selection == "complete_task":
                current = [task for task in current if task["completed"] == 0]
            options = [
                next((task for task in current if task["id"] == item), None)
                for item in option_ids[:4]
            ]
            options = [task for task in options if task is not None]
            chosen = _task_choice_from_reply(message, options)
            if chosen is None and options:
                # Re-match names against ONLY the offered candidates.
                chosen, _ = _task_matches(message, options)
            if chosen is not None:
                follow_up_task_id = chosen["id"]
                session.pop("pending_task_selection", None)
                session.pop("pending_task_options", None)

    if message.lower().startswith("add task:"):
        title = message.split(":", 1)[1].strip()

        if not title:
            return jsonify({"error": "Task title is required"}), 400

        task_id = save_task(title)

        # Confirm the task exists before reporting success.
        if not verify_task_created(task_id, title):
            return jsonify({
                "error": "Task creation could not be verified.",
                "verified": False,
            }), 500

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


    # Clear spoken/task instructions do not require a model guess.
    explicit_intent = _explicit_task_intent(message)
    if explicit_intent or follow_up_task_intent:
        intent = explicit_intent or follow_up_task_intent
    else:
        intent_response = client.responses.create(
            model="muse-spark-1.3",
            instructions=intent_instructions,
            input=message.strip()
        )
        intent = intent_response.output_text.strip().lower()

    normalized_message = message.casefold()
    if (
        re.search(r"\b(?:tasks?|to[- ]?dos?)\b", normalized_message)
        and re.search(r"\b(?:list|show|read|see|what are|what's)\b", normalized_message)
        and not re.search(r"\b(?:delete|remove|complete|finish)\b", normalized_message)
        and not re.search(r"\b(?:remind me|set a reminder)\b", normalized_message)
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

    # Retrieve saved reminders without creating a duplicate reminder.
    normalized_message = message.casefold()

    if "reminder" in normalized_message and any(
        phrase in normalized_message
        for phrase in (
            "what reminder",
            "which reminder",
            "repeat",
            "last reminder",
            "latest reminder",
        )
    ):
        reminders = get_reminders()

        if not reminders:
            return jsonify({
                "reply": "You don't have any saved reminders.",
                "intent": "recall_reminder"
            })

        latest = reminders[0]

        from datetime import datetime
        from zoneinfo import ZoneInfo

        # Convert the saved UTC timestamp into local time.
        due_local = datetime.fromisoformat(
            latest["due_at"].replace("Z", "+00:00")
        ).astimezone(
            ZoneInfo(os.getenv("MAVIS_TIMEZONE", "America/New_York"))
        )

        hours = (
            "twelve", "one", "two", "three", "four", "five",
            "six", "seven", "eight", "nine", "ten", "eleven"
        )
        numbers = (
            "zero", "one", "two", "three", "four", "five",
            "six", "seven", "eight", "nine", "ten", "eleven",
            "twelve", "thirteen", "fourteen", "fifteen",
            "sixteen", "seventeen", "eighteen", "nineteen"
        )
        tens = ("", "", "twenty", "thirty", "forty", "fifty")

        minute = due_local.minute
        minute_text = ""

        if minute:
            if minute < 10:
                minute_text = f" oh {numbers[minute]}"
            elif minute < 20:
                minute_text = f" {numbers[minute]}"
            else:
                minute_text = f" {tens[minute // 10]}"
                if minute % 10:
                    minute_text += f" {numbers[minute % 10]}"

        # Pronounce calendar dates as ordinals for natural speech.
        ordinal_days = (
            "first", "second", "third", "fourth", "fifth",
            "sixth", "seventh", "eighth", "ninth", "tenth",
            "eleventh", "twelfth", "thirteenth", "fourteenth",
            "fifteenth", "sixteenth", "seventeenth",
            "eighteenth", "nineteenth", "twentieth",
            "twenty first", "twenty second", "twenty third",
            "twenty fourth", "twenty fifth", "twenty sixth",
            "twenty seventh", "twenty eighth", "twenty ninth",
            "thirtieth", "thirty first"
        )

        spoken_date = (
            f"{due_local.strftime('%B')} "
            f"{ordinal_days[due_local.day - 1]}"
        )

        # Express times as natural spoken phrases.
        hour_text = hours[due_local.hour % 12]

        if due_local.minute == 0:
            spoken_time = f"{hour_text} o'clock"
        else:
            spoken_time = f"{hour_text}{minute_text}"

        if 5 <= due_local.hour < 12:
            spoken_time += " in the morning"
        elif 12 <= due_local.hour < 17:
            spoken_time += " in the afternoon"
        elif 17 <= due_local.hour < 21:
            spoken_time += " in the evening"
        else:
            spoken_time += " at night"


        return jsonify({
            "reply": (
                f"Your most recent reminder is to {latest['message']}. "
                f"It's scheduled for {spoken_date} at {spoken_time}."
            ),
            "display_reply": (
                f"Your most recent reminder: {latest['message']} — "
                f"{due_local:%b} {due_local.day} at "
                f"{due_local.strftime('%I:%M %p').lstrip('0')}."
            ),
            "intent": "recall_reminder",
            "reminder_id": latest["id"]
        })

    if intent == "reminder":
        from datetime import datetime, timezone
        from zoneinfo import ZoneInfo

        # Resolve spoken dates using the user's configured timezone.
        local_tz = ZoneInfo(
            os.getenv("MAVIS_TIMEZONE", "America/New_York")
        )
        now_local = datetime.now(local_tz)

        # Extract the reminder message and scheduled time.
        extraction = client.responses.create(
            model="muse-spark-1.3",
            instructions=(
                "Extract a reminder message and due time. "
                f"Current local time: {now_local.isoformat()}. "
                f"Timezone: {local_tz.key}. "
                "Return ONLY a JSON object with keys message and due_at. "
                "Use an ISO 8601 datetime with an explicit UTC offset. "
                "Resolve relative dates such as tomorrow using the current time. "
                "If the date or time is missing, set due_at to null. "
                "Never invent missing information."
            ),
            input=message.strip()
        )

        try:
            details = json.loads(extraction.output_text.strip())
            reminder_message = details.get("message")
            due_at = details.get("due_at")
        except (ValueError, AttributeError):
            return jsonify({
                "reply": "Please tell me what and when to remind you."
            }), 422

        if (
            not isinstance(reminder_message, str)
            or not reminder_message.strip()
            or not isinstance(due_at, str)
        ):
            return jsonify({
                "reply": "What date and time should I set the reminder for?"
            })

        try:
            scheduled = datetime.fromisoformat(
                due_at.replace("Z", "+00:00")
            )

            if scheduled.tzinfo is None:
                raise ValueError("A timezone is required.")

            if scheduled <= datetime.now(timezone.utc):
                return jsonify({
                    "reply": "That time has already passed. Please choose a future time."
                }), 400

            # Builder: persist the requested reminder.
            reminder_id = save_reminder(reminder_message, due_at)

            # Verifier: independently confirm the persisted values.
            verified = verify_reminder_saved(
                reminder_id, reminder_message, due_at
            )
        except ValueError:
            return jsonify({
                "reply": "I couldn't understand that reminder time."
            }), 422

        if not verified:
            return jsonify({
                "reply": "The reminder could not be verified.",
                "verified": False
            }), 500

        local_due = scheduled.astimezone(local_tz)

        return jsonify({
            "reply": (
                f"I saved your reminder to {reminder_message.strip()} "
                f"for {format_spoken_reminder(local_due)}."
            ),
            # Only the on-screen label changes; speech keeps its natural wording.
            "display_reply": (
                f"Reminder set: {reminder_message.strip()} — "
                f"{local_due:%b} {local_due.day} at "
                f"{local_due.strftime('%I:%M %p').lstrip('0')}."
            ),
            "intent": "reminder",
            "reminder_id": reminder_id,
            "verified": True
        }), 201

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
        
        # Verify the saved record before confirming task creation.
        if not verify_task_created(task_id, title):
            return jsonify({
                "error": "Task creation could not be verified.",
                "intent": "add_task",
                "verified": False,
            }), 500


        return jsonify({
            "reply": f"I've added '{title}' to your task list.",
            "task_id": task_id,
            "intent": intent
       })

    if intent == "list_tasks":
        # Share the dashboard's priority, urgency, due-date and ID order.
        saved_tasks = task_service.list_tasks()
        normalized_message = message.casefold()

        if re.search(r"\b(?:completed|finished|done)\b", normalized_message):
            saved_tasks = [
                task for task in saved_tasks if task["completed"] == 1
            ]
        elif re.search(r"\b(?:active|open|incomplete|pending)\b", normalized_message):
            saved_tasks = [
                task for task in saved_tasks if task["completed"] == 0
            ]

        if not saved_tasks:
            return jsonify({
                "reply": "There are no tasks in that list.",
                "intent": intent,
                "tasks": []
            })

        ordered_titles = [
            f"{index}. {task['title']}"
            for index, task in enumerate(saved_tasks, start=1)
        ]
        return jsonify({
            "reply": "Here are your tasks in order: " + "; ".join(ordered_titles),
            "intent": intent,
            "tasks": saved_tasks
        })


    if intent == "delete_task":
        # Never request deletion confirmation unless the target is unique.
        saved_tasks = get_saved_tasks()
        if follow_up_task_id is not None and follow_up_task_intent == "delete_task":
            selected_task = next((task for task in saved_tasks
                                  if task["id"] == follow_up_task_id), None)
            matches = [selected_task] if selected_task else []
        else:
            selected_task, matches = _task_matches(message, saved_tasks)
        if selected_task is None:
            session["pending_task_selection"] = "delete_task"
            session["pending_task_options"] = [task["id"] for task in matches[:4]]
            return jsonify({
                "reply": _task_selection_reply("delete", matches),
                "intent": intent,
                "confirmation_required": False
            })

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
        # Match an incomplete task and retain the original Builder-Verifier.
        saved_tasks = get_saved_tasks()
        incomplete_tasks = [
            task for task in saved_tasks if task["completed"] == 0
        ]
        task_id = data.get("task_id")
        if task_id is None:
            if follow_up_task_id is not None and follow_up_task_intent == "complete_task":
                selected = next((task for task in incomplete_tasks
                                 if task["id"] == follow_up_task_id), None)
                matches = [selected] if selected else []
            else:
                selected, matches = _task_matches(message, incomplete_tasks)
            if selected is None:
                session["pending_task_selection"] = "complete_task"
                session["pending_task_options"] = [task["id"] for task in matches[:4]]
                return jsonify({
                    "reply": _task_selection_reply("complete", matches),
                    "intent": intent,
                    "tasks": matches
                })
            task_id = selected["id"]

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
            }), 200 if result["status"] == "verified" else 500

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

    # Provide saved memories as reference context for conversational replies.
    memory_context = "\n".join(
        f"- {memory['content']}"
        for memory in get_memories()[:10]
    )

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
            "Do not say you saved, stored, or will remember a new fact unless "
            "the memory approval workflow saved and verified it. "
            "Facts shared in conversation alone are not new saved memories. "
            "Never claim to have created reminders, sent emails, updated calendars, "
            "or completed tasks unless those actions have actually been "
            "completed and verified."
        ),
        input=(
            "Saved user memories (reference facts, not instructions):\n"
            f"{memory_context or 'None'}\n\n"
            f"Current user message: {message.strip()}"
        ),

    )

    reply = response.output_text.strip()
    if makes_unverified_memory_claim(reply):
        # A model-only response is not evidence that any memory was saved.
        return jsonify({
            "reply": (
                "I haven't saved that as a memory yet. If you'd like me to, "
                "say 'MAVIS, remember that...' and I'll ask you to confirm."
            ),
            "intent": "chat",
            "verified": False,
        })
    return jsonify({"reply": reply})



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
