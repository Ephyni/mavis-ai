let tasks = [],
  taskActivity = [],
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
  const [r, activity] = await Promise.all([
    api("/api/tasks?today=" + today),
    api("/api/task-activity"),
  ]);
  tasks = r.tasks;
  taskActivity = activity.events;
  recommendation = r.recommendation;
  render();
}

async function speakResponse(text) {
  // Request synthesized speech without modifying task state.
  if (typeof text !== "string" || !text.trim()) return;
  if (!voiceResponsesEnabled()) {
    setOrbState("idle");
    return;
  }

  // Measure time to speech and retain a length metric without logging content.
  const speechStartedAt = performance.now();

  // Remove Markdown formatting before speech synthesis.
  const spokenText = text
    .replace(/\*\*(.*?)\*\*/g, "$1")
    .replace(/\*(.*?)\*/g, "$1")
    .replace(/\s+/g, " ")
    .trim();

  console.info("MAVIS latency | speech length:", spokenText.length, "characters");
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
    console.info(
      "MAVIS latency | speech request to playback:",
      Math.round(performance.now() - speechStartedAt),
      "ms"
    );
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

const displayedReminderIds = new Set();

async function checkDueReminders() {
  // Retrieve reminders that have reached their scheduled time.
  try {
    const result = await api("/api/reminders/due");

    for (const reminder of result.reminders) {
      // Avoid displaying the same reminder twice during this session.
      if (displayedReminderIds.has(reminder.id)) continue;
      displayedReminderIds.add(reminder.id);

      // Display the reminder without interrupting the task dashboard.
      const notification = document.createElement("div");
      notification.setAttribute("role", "alert");
      notification.style.cssText = `
        position: fixed;
        bottom: 24px;
        right: 24px;
        z-index: 9999;
        background: #19213e;
        color: white;
        border: 1px solid #5ccfe6;
        border-radius: 12px;
        padding: 16px;
        max-width: 340px;
        box-shadow: 0 8px 24px #0006;
      `;

      const message = document.createElement("p");
      message.textContent = `🔔 MAVIS Reminder: ${reminder.message}`;

      const dismiss = document.createElement("button");
      dismiss.textContent = "Dismiss";

      // Acknowledge only when the user dismisses the notification.
      dismiss.addEventListener("click", async () => {
        try {
          await api(
            `/api/reminders/${reminder.id}/acknowledge`,
            "POST"
          );
          notification.remove();
        } catch (error) {
          console.error("Reminder acknowledgment failed:", error);
        }
      });

      notification.append(message, dismiss);
      document.body.appendChild(notification);

      // Reuse the existing Kokoro ONNX speech system.
      try {
        await speakResponse(
          `You asked me to remind you to ${reminder.message}.`
        );
      } catch (error) {
        console.warn("Reminder audio could not play:", error);
      }
    }
  } catch (error) {
    console.error("Reminder check failed:", error);
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
        change(remove, "/api/tasks/" + t.id, "DELETE", { confirm: true });
    };
    card.append(toggle, remove);
    list.append(card);
  }
  renderHomeSummary();
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
document.querySelector("#task-form").onsubmit = async (e) => {
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

voiceStatus.textContent = result.display_reply || result.reply || "Voice command processed successfully.";

// Begin voice playback before waiting for the task and memory refreshes.
const speechPromise =
  typeof result.reply === "string" && result.reply.trim()
    ? speakResponse(result.spoken_reply || result.reply).catch((speechError) => {
        console.error("MAVIS speech playback failed:", speechError);
      })
    : Promise.resolve();

// Keep verified records in sync independently of speech generation.
await Promise.all([
  load(),
  refreshMemoryAfterConversation(result),
  speechPromise,
]);

    } catch (error) {
      voiceStatus.textContent = error.message;
      setOrbState("idle");
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

function startReminderChecks() {
  // Check immediately, then poll while the MAVIS page is open.
  checkDueReminders();
  setInterval(checkDueReminders, 15000);
}

if (document.readyState === "loading") {
  document.addEventListener(
    "DOMContentLoaded",
    startReminderChecks,
    { once: true }
  );
} else {
  startReminderChecks();
}


// Ground the Home overview in actual task records, not simulated activity.
function renderHomeSummary() {
  const active = document.querySelector("#home-tasks");
  const recent = document.querySelector("#recent-activity");
  if (!active || !recent) return;
  active.replaceChildren();
  recent.replaceChildren();

  const open = tasks.filter((task) => !task.completed).slice(0, 3);
  if (!open.length) {
    active.append(node("p", "No open tasks. You're all caught up."));
  }
  for (const task of open) {
    const item = node("div", "");
    item.className = "mini-task";
    const title = node("strong", task.title);
    const detail = node("span", task.due_date ? "Due " + task.due_date : "No deadline");
    item.append(title, detail);
    active.append(item);
  }

  // Display actual events, not task creation order or current task state.
  const activityLabels = {
    created: "Saved task",
    completed: "Completed task",
    deleted: "Deleted task",
    reopened: "Reopened task",
  };
  if (!taskActivity.length) {
    recent.append(node("p", "New task activity will appear here."));
  }
  for (const event of taskActivity.slice(0, 2)) {
    const item = node("div", "");
    item.className = "activity-entry";
    const memoryEvent = event.entity_type === "memory";
    const activityLabel = memoryEvent
      ? (event.action === "created" ? "Saved memory"
        : event.action === "deleted" ? "Deleted memory" : "Memory activity")
      : (activityLabels[event.action] || "Task activity");
    item.append(
      node("strong", activityLabel),
      node("span", event.title),
    );
    recent.append(item);
  }
}

// Navigation changes only which view is visible; it does not replace the page.
const mavisViews = ["home", "tasks", "memory", "settings"];
function activateView() {
  const requested = window.location.hash.slice(1);
  const view = mavisViews.includes(requested) ? requested : "home";
  document.body.classList.toggle("home-active", view === "home");
  for (const screen of document.querySelectorAll(".view-screen")) {
    screen.hidden = screen.id !== "view-" + view;
  }
  for (const button of document.querySelectorAll(".mavis-nav [data-view]")) {
    button.setAttribute("aria-pressed", String(button.dataset.view === view));
  }
  if (view === "memory") {
    void loadMavisMemories();
  }
}
document.querySelectorAll("[data-view]").forEach((button) => {
  button.addEventListener("click", () => {
    const hash = "#" + button.dataset.view;
    if (window.location.hash === hash) activateView();
    else window.location.hash = hash;
  });
});
window.addEventListener("hashchange", activateView);
activateView();

// The Memory screen uses the app's existing save, list, and approval APIs.
async function loadMavisMemories() {
  const saved = document.querySelector("#memories-list");
  const pending = document.querySelector("#proposals-list");
  const fetchStatus = document.querySelector("#memory-fetch-status");
  fetchStatus.textContent = "";
  try {
    const [memoryResult, proposalResult] = await Promise.all([
      api("/api/memories"),
      api("/api/memory-proposals"),
    ]);
    saved.replaceChildren();
    pending.replaceChildren();

    if (!memoryResult.memories.length) {
      saved.append(node("p", "No memories saved yet."));
    }
    for (const memory of memoryResult.memories) {
      const item = node("div", "");
      item.className = "memory-item";
      item.append(
        node("p", memory.content),
        node("small", memory.category || "general"),
      );
      const actions = node("div", "");
      actions.className = "memory-actions";
      const remove = node("button", "Delete");
      remove.type = "button";
      remove.setAttribute("aria-label", "Delete saved memory");
      remove.onclick = async () => {
        if (!window.confirm("Permanently delete this saved memory?")) return;
        remove.disabled = true;
        try {
          const result = await api(
            "/api/memories/" + memory.id, "DELETE", { confirm: true },
          );
          if (!result.verified) throw Error("Deletion was not verified.");
          await loadMavisMemories();
          await load(); // Make the new event appear at the top of Home.
          document.querySelector("#memory-status").textContent =
            "Saved memory deleted and verified.";
        } catch (error) {
          fetchStatus.textContent = error.message;
          remove.disabled = false;
        }
      };
      actions.append(remove);
      item.append(actions);
      saved.append(item);
    }

    if (!proposalResult.proposals.length) {
      pending.append(node("p", "No memories awaiting approval."));
    }
    for (const proposal of proposalResult.proposals) {
      const item = node("div", "");
      item.className = "memory-item";
      item.append(node("p", proposal.content));
      const actions = node("div", "");
      actions.className = "memory-actions";
      const approve = node("button", "Approve");
      approve.type = "button";
      approve.className = "approve";
      const reject = node("button", "Reject");
      reject.type = "button";
      for (const [button, action] of [[approve, "approve"], [reject, "reject"]]) {
        button.onclick = async () => {
          approve.disabled = true;
          reject.disabled = true;
          try {
            await api("/api/memory-proposals/" + proposal.id + "/" + action, "POST");
            await loadMavisMemories();
            if (action === "approve") {
              await load(); // Show the approved memory in Recent Activity.
            }
          } catch (error) {
            fetchStatus.textContent = error.message;
            approve.disabled = false;
            reject.disabled = false;
          }
        };
      }
      actions.append(approve, reject);
      item.append(actions);
      pending.append(item);
    }
  } catch (error) {
    fetchStatus.textContent = "Unable to load memories: " + error.message;
  }
}

// Keep the Memory view current when Home creates, approves, or deletes a memory.
// Refresh only after the backend reports a state change or pending proposal.
async function refreshMemoryAfterConversation(result) {
  if (!result || !["save_memory", "delete_memory"].includes(result.intent)) {
    return;
  }
  if (
    result.verified === true ||
    result.pending_approval === true ||
    result.cancelled === true
  ) {
    await loadMavisMemories();
  }
}

document.querySelector("#memory-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const content = document.querySelector("#memory-content").value.trim();
  const saveButton = form.querySelector('button[type="submit"]');
  const memoryStatus = document.querySelector("#memory-status");
  if (!content) return;
  saveButton.disabled = true;
  try {
    await api("/api/memories", "POST", { content });
    form.reset();
    memoryStatus.textContent = "Memory saved.";
    await loadMavisMemories();
    await load(); // Refresh Home's activity list after a direct save.
  } catch (error) {
    memoryStatus.textContent = error.message;
  } finally {
    saveButton.disabled = false;
  }
});

// Keep the Home screen compact without discarding earlier chat messages.
const chatLog = document.querySelector("#chat-log");
const historyButton = document.querySelector("#chat-history-button");
const historyDialog = document.querySelector("#chat-history-dialog");
const historyList = document.querySelector("#chat-history-list");

function updateChatPreview() {
  const messages = [...chatLog.querySelectorAll(".chat-message")];
  messages.forEach((item, index) => {
    item.hidden = index < messages.length - 2;
  });
  historyButton.hidden = messages.length === 0;
}

historyButton.addEventListener("click", () => {
  historyList.replaceChildren();
  for (const message of chatLog.querySelectorAll(".chat-message")) {
    const bubble = node("p", message.textContent);
    bubble.className = message.className;
    historyList.append(bubble);
  }
  historyDialog.showModal();
});
document.querySelector("#chat-history-close").addEventListener("click", () => {
  historyDialog.close();
});

// Text messages share the same Flask /api/chat route and verification logic as voice.
function addMavisChatMessage(role, message) {
  chatLog.querySelector(".chat-placeholder")?.remove();
  const bubble = node("p", message);
  bubble.className = "chat-message " + role;
  chatLog.append(bubble);
  updateChatPreview();
}
document.querySelector("#chat-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const input = document.querySelector("#chat-input");
  const send = document.querySelector("#send-chat");
  const message = input.value.trim();
  if (!message) return;
  // Clear stale voice results when a new typed conversation starts.
  if (!mediaRecorder || mediaRecorder.state !== "recording") {
    voiceStatus.textContent = "";
  }
  input.value = "";
  send.disabled = true;
  addMavisChatMessage("user", message);
  try {
    const response = await api("/api/chat", "POST", { message });
    addMavisChatMessage("assistant", response.display_reply || response.reply || "Your request was processed.");
    // Text replies start speech generation while UI data refreshes.
    const speechPromise = response.reply
      ? speakResponse(response.spoken_reply || response.reply).catch((error) => {
          console.warn("Voice playback failed:", error);
        })
      : Promise.resolve();
    await Promise.all([
      load(),
      refreshMemoryAfterConversation(response),
      speechPromise,
    ]);
  } catch (error) {
    addMavisChatMessage("error", "MAVIS couldn't complete that request: " + error.message);
  } finally {
    send.disabled = false;
    input.focus();
  }
});

// These settings are browser-local controls, not new server-side preferences.
const voiceSetting = document.querySelector("#voice-playback-setting");
const motionSetting = document.querySelector("#reduce-motion-setting");
function readPreference(key, fallback) {
  try {
    const saved = localStorage.getItem(key);
    return saved === null ? fallback : saved === "true";
  } catch {
    return fallback;
  }
}
function writePreference(key, value) {
  try {
    localStorage.setItem(key, String(value));
  } catch {
    // The preference still works for this page if browser storage is unavailable.
  }
}
function voiceResponsesEnabled() {
  return voiceSetting?.checked !== false;
}
voiceSetting.checked = readPreference("mavis.voicePlayback", true);
motionSetting.checked = readPreference("mavis.reduceMotion", false);

// All orb effects now use CSS, including the luminous strand tracers.
const systemMotionPreference = window.matchMedia("(prefers-reduced-motion: reduce)");
function syncOrbMotionPreference() {
  const reduced = motionSetting.checked || systemMotionPreference.matches;
  document.body.classList.toggle("reduce-motion", reduced);
}
syncOrbMotionPreference();

voiceSetting.addEventListener("change", () => {
  writePreference("mavis.voicePlayback", voiceSetting.checked);
});
motionSetting.addEventListener("change", () => {
  syncOrbMotionPreference();
  writePreference("mavis.reduceMotion", motionSetting.checked);
});
if (typeof systemMotionPreference.addEventListener === "function") {
  systemMotionPreference.addEventListener("change", syncOrbMotionPreference);
}
