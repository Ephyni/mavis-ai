
from flask import Flask, jsonify, request

from memory import init_db, save_memory, get_memories

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
    return jsonify({"tasks": tasks})

@app.post("/api/tasks")
def create_task():
    data = request.get_json(silent=True) or {}
    title = data.get("title")

    if not isinstance(title, str) or not title.strip():
        return jsonify({"error": "Task title is required"}), 400

    task = {
        "id": len(tasks) + 1,
        "title": title.strip(),
        "completed": False
    }

    tasks.append(task)
    return jsonify(task), 201

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

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)