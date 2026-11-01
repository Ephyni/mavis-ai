let tasks = [],
  filter = "open",
  recommendation = null;
const status = document.querySelector("#status");
function node(tag, text) {
  const n = docuFment.createElement(tag);
  n.textContent = text;
  return n;
}
async function api(url, method = "GET", data) {
  const r = await fetch(url, {
    method,
    headers: { "Content-Type": "application/json" },
    ...(data ? { body: JSON.stringify(data) } : {}),
  });
  const v = await r.json();
  if (!r.ok) throw Error(v.error || "Request failed");
  return v;
}
async function load() {
  const d = new Date(),
    today = [
      d.getFullYear(),
      String(d.getMonth() + 1).padStart(2, "0"),
      String(d.getDate()).padStart(2, "0"),
    ].join("-");
  const r = await api("/api/tasks?today=" + today);
  tasks = r.tasks;
  recommendation = r.recommendation;
  render();
}
function render() {
  document.querySelector("#next").textContent = recommendation
    ? recommendation.title + ": " + recommendation.reason
    : "You’re all caught up. Add a task when you’re ready.";
  const list = document.querySelector("#list");
  list.replaceChildren();
  const visible = tasks.filter((t) =>
    filter === "completed"
      ? t.completed
      : !t.completed && (filter !== "today" || t.due_today || t.overdue),
  );
  if (!visible.length) list.append(node("p", "No tasks in this view."));
  for (const t of visible) {
    const card = node("article", "");
    const badge = node(
      "span",
      t.completed
        ? "Completed"
        : t.urgency.toUpperCase() + (t.overdue ? " · OVERDUE" : ""),
    );
    badge.className = "badge " + t.urgency;
    card.append(
      badge,
      node("h3", t.title),
      node(
        "p",
        (t.due_date ? "Due " + t.due_date : "No deadline") +
          " · " +
          t.estimated_minutes +
          " minutes · Importance: " +
          t.priority,
      ),
    );
    const toggle = node("button", t.completed ? "Reopen" : "Mark complete");
    toggle.onclick = () =>
      change(toggle, "/api/tasks/" + t.id, "PATCH", {
        completed: !t.completed,
      });
    const remove = node("button", "Delete");
    remove.setAttribute("aria-label", "Delete " + t.title);
    remove.onclick = () => {
      if (confirm('Delete "' + t.title + '"?'))
        change(remove, "/api/tasks/" + t.id, "DELETE");
    };
    card.append(toggle, remove);
    list.append(card);
  }
}
async function change(button, url, method, data) {
  button.disabled = true;
  try {
    await api(url, method, data);
    await load();
    status.textContent = "Saved.";
  } catch (e) {
    status.textContent = e.message;
  } finally {
    button.disabled = false;
  }
}
document.querySelector("form").onsubmit = async (e) => {
  e.preventDefault();
  const f = e.currentTarget,
    b = f.querySelector("button"),
    data = Object.fromEntries(new FormData(f));
  data.estimated_minutes = Number(data.estimated_minutes);
  b.disabled = true;
  try {
    await api("/api/tasks", "POST", data);
    f.reset();
    await load();
    status.textContent = "Task added.";
  } catch (e) {
    status.textContent = e.message;
  } finally {
    b.disabled = false;
  }
};
document.querySelectorAll("[data-filter]").forEach(
  (b) =>
    (b.onclick = () => {
      filter = b.dataset.filter;
      document
        .querySelectorAll("[data-filter]")
        .forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
      render();
    }),
);
document.querySelector("#speak").onclick = () => {
  if (!window.speechSynthesis) {
    status.textContent = "Speech is unavailable in this browser.";
    return;
  }
  speechSynthesis.cancel();
  speechSynthesis.speak(
    new SpeechSynthesisUtterance(document.querySelector("#next").textContent),
  );
};
document.querySelector("#stop").onclick = () =>
  window.speechSynthesis?.cancel();
load().catch((e) => {
  status.textContent = e.message;
  document.querySelector("#next").textContent = "Unable to load tasks.";
});

// Reference the voice controls in MAVIS's interface.
const recordButton = document.querySelector("#record-voice");
const stopButton = document.querySelector("#stop-recording");
const voiceStatus = document.querySelector("#voice-status");

let mediaRecorder = null;
let audioChunks = [];

// Start microphone capture when the user initiates a voice command.
recordButton.onclick = async () => {
  try {
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: true,
    });

    audioChunks = [];
    mediaRecorder = new MediaRecorder(stream);

    mediaRecorder.ondataavailable = (event) => {
      if (event.data.size > 0) {
        audioChunks.push(event.data);
      }
    };

    mediaRecorder.start();

    recordButton.disabled = true;
    stopButton.disabled = false;

    voiceStatus.textContent = "MAVIS is listening...";
  } catch (error) {
    voiceStatus.textContent = "Microphone access failed.";
    console.error(error);
  }
};

// Stop recording and send the captured audio to MAVIS.
stopButton.onclick = () => {
  if (!mediaRecorder || mediaRecorder.state !== "recording") {
    return;
  }

  stopButton.disabled = true;
  voiceStatus.textContent = "Processing your voice command...";

  mediaRecorder.onstop = async () => {
    // Release the microphone after recording.
    mediaRecorder.stream.getTracks().forEach((track) => track.stop());

    const audioBlob = new Blob(audioChunks, {
      type: mediaRecorder.mimeType,
    });

    const formData = new FormData();
    formData.append("audio", audioBlob, "recording.webm");

    try {
      const response = await fetch("/api/voice", {
        method: "POST",
        body: formData,
      });

      const result = await response.json();

      if (!response.ok) {
        throw new Error(result.error || "Voice command failed.");
      }

      voiceStatus.textContent = "Voice command processed successfully.";

      // Refresh tasks to display any changes made by MAVIS.
      await load();
    } catch (error) {
      voiceStatus.textContent = error.message;
      console.error(error);
    } finally {
      recordButton.disabled = false;
    }
  };

  mediaRecorder.stop();
};
