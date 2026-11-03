let tasks = [],
  filter = "open",
  recommendation = null;
const status = document.querySelector("#status");
function node(tag, text) {
  const n = document.createElement(tag);
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

async function speakResponse(text) {
  // Request synthesized speech without modifying task state.
  if (typeof text !== "string" || !text.trim()) return;

  // Remove Markdown formatting before speech synthesis.
  const spokenText = text
    .replace(/\*\*(.*?)\*\*/g, "$1")
    .replace(/\*(.*?)\*/g, "$1")
    .replace(/\s+/g, " ")
    .trim();

  const response = await fetch("/api/tts", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text: spokenText.slice(0, 300) }),
  });


  if (!response.ok) {
    throw new Error("Speech generation failed.");
  }

  // Convert the returned audio into a playable browser URL.
  const audioBlob = await response.blob();
  const audioUrl = URL.createObjectURL(audioBlob);
  const audio = new Audio(audioUrl);

  // Slightly increase speaking pace for a conversational delivery.
  audio.playbackRate = 1.15;

  // Synchronize the orb with actual audio playback.
  audio.addEventListener("playing", () => {
    setOrbState("speaking");
  });

  // Restore the idle state and release audio resources.
  const cleanup = () => {
    setOrbState("idle");
    URL.revokeObjectURL(audioUrl);
  };

  audio.addEventListener("ended", cleanup, { once: true });
  audio.addEventListener("error", cleanup, { once: true });


  try {
    await audio.play();
  } catch (error) {
    cleanup();
    throw error;
  }
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

// Update MAVIS's visual state without changing voice processing.
const mavisOrb = document.querySelector("#mavis-orb");

function setOrbState(state) {
  const validStates = ["idle", "listening", "thinking", "speaking"];

  if (!validStates.includes(state) || !mavisOrb) {
    return;
  }

  mavisOrb.dataset.state = state;
  mavisOrb.setAttribute(
    "aria-label",
    `MAVIS voice assistant is ${state}`
  );
}

let mediaRecorder = null;
let audioChunks = [];

// Track microphone activity to detect when the user finishes speaking.
let audioContext = null;
let audioAnalyser = null;
let silenceCheckTimer = null;
let recordingStartedAt = 0;
let lastSpeechAt = 0;
let speechDetected = false;

const SILENCE_DURATION_MS = 1500;
const MAX_RECORDING_MS = 20000;
const MIN_SPEECH_LEVEL = 0.025;


function startSilenceDetection(stream) {
  // Monitor microphone volume without changing the recorded audio.
  audioContext = new AudioContext();
  audioAnalyser = audioContext.createAnalyser();
  audioAnalyser.fftSize = 2048;

  const source = audioContext.createMediaStreamSource(stream);
  source.connect(audioAnalyser);

  const samples = new Uint8Array(audioAnalyser.fftSize);

  recordingStartedAt = Date.now();
  lastSpeechAt = recordingStartedAt;
  speechDetected = false;

  silenceCheckTimer = setInterval(() => {
    if (!mediaRecorder || mediaRecorder.state !== "recording") {
      return;
    }

    audioAnalyser.getByteTimeDomainData(samples);

    // Calculate the microphone signal's root-mean-square volume.
    let sumSquares = 0;

    for (const sample of samples) {
      const normalized = (sample - 128) / 128;
      sumSquares += normalized * normalized;
    }

    const volume = Math.sqrt(sumSquares / samples.length);
    const now = Date.now();

    if (volume > MIN_SPEECH_LEVEL) {
      speechDetected = true;
      lastSpeechAt = now;
    }

    const silenceElapsed = now - lastSpeechAt;
    const recordingElapsed = now - recordingStartedAt;

    if (
      (speechDetected && silenceElapsed >= SILENCE_DURATION_MS) ||
      recordingElapsed >= MAX_RECORDING_MS
    ) {
      stopButton.click();
    }
  }, 100);
}


function stopSilenceDetection() {
  // Stop monitoring microphone activity after recording ends.
  if (silenceCheckTimer !== null) {
    clearInterval(silenceCheckTimer);
    silenceCheckTimer = null;
  }

  // Release the audio analysis resources.
  if (audioContext) {
    const context = audioContext;
    audioContext = null;
    audioAnalyser = null;
    void context.close();
  }

  speechDetected = false;
}

// Start microphone capture when the user initiates a voice command.
recordButton.onclick = async () => {
  try {
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: true,
    });

    audioChunks = [];
    mediaRecorder = new MediaRecorder(stream);

  // Change the orb to listening when recording begins.
  mediaRecorder.addEventListener("start", () => {
    setOrbState("listening");
  });

    mediaRecorder.ondataavailable = (event) => {
      if (event.data.size > 0) {
        audioChunks.push(event.data);
      }
    };

    mediaRecorder.start();

    // Automatically detect when the user finishes speaking.
    startSilenceDetection(stream);

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

// Stop monitoring microphone activity before processing the command.
stopSilenceDetection();

  stopButton.disabled = true;
  voiceStatus.textContent = "Processing your voice command...";

  // Show the thinking state while MAVIS processes the voice command.
  setOrbState("thinking");

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

voiceStatus.textContent = result.reply || "Voice command processed successfully.";

// Refresh tasks to display any changes made by MAVIS.
await load();

// Speak the response returned by the conversational backend.
if (typeof result.reply === "string" && result.reply.trim()) {
  try {
    await speakResponse(result.reply);
  } catch (speechError) {
    console.error("MAVIS speech playback failed:", speechError);
  }
}

    } catch (error) {
      voiceStatus.textContent = error.message;
      console.error(error);
    } finally {
      recordButton.disabled = false;
    }
  };

  mediaRecorder.stop();
};

// Start a voice command when the user clicks the orb.
mavisOrb.addEventListener("click", () => {
  if (!recordButton.disabled) {
    recordButton.click();
  }
});