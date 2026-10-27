
from flask import Flask, jsonify, request
import os
from dotenv import load_dotenv
from openai import OpenAI
from memory import get_tasks as get_saved_tasks
from memory import save_task

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

tasks = []

@app.get("/")
def home():
    return jsonify({
        "assistant": "MAVIS",
        "message": "MAVIS backend is running!"
    })

@app.get("/api/tasks")
def get_tasks():
    tasks = get_saved_tasks()
    return jsonify({"tasks": tasks})

@app.post("/api/tasks")
def create_task():
    data = request.get_json(silent=True) or {}
    title = data.get("title")

    if not isinstance(title, str) or not title.strip():
        return jsonify({"error": "Task title is required"}), 400

    task_id = save_task(title.strip())

    return jsonify({
    "id": task_id,
    "title": title.strip(),
    "completed": 0
}), 201


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
def chat():
    data = request.get_json(silent=True) or {}
    message = data.get("message")

    if not isinstance(message, str) or not message.strip():
        return jsonify({"error": "Message is required"}), 400

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
        "'add_task', 'list_tasks', 'reminder', or 'chat'. "
        "Use 'list_tasks' when the user asks to see or hear their tasks. "
        "Do not perform any actions. "
        "Reply with only the classification."
    )

    intent_response = client.responses.create(
        model="muse-spark-1.3",
        instructions=intent_instructions,
        input=message.strip()
    )

    intent = intent_response.output_text.strip().lower()
    print("Detected intent:", intent)

    if intent not in {"add_task", "list_tasks", "reminder", "chat"}:
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

        if not saved_tasks:
            return jsonify({
                "reply": "You don't have any saved tasks yet.",
                "intent": intent,
                "tasks": []
            })

        task_titles = [task["title"] for task in saved_tasks]

        return jsonify({
            "reply": "Here are your tasks: " + ", ".join(task_titles),
            "intent": intent,
            "tasks": saved_tasks
        })

    response = client.responses.create(
    model="muse-spark-1.3",
    instructions=(
        "You are MAVIS, a friendly, intelligent AI productivity assistant. "
        "Help users organize tasks, plan their schedules, and stay productive. "
        "Be conversational, clear, supportive, and concise. "
        "Never claim to have created reminders, sent emails, or updated calendars "
        "unless those actions have actually been completed and verified."
    ),
    input=message.strip()
)

    return jsonify({"reply": response.output_text})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)