const pet = document.querySelector("#pet");
const sprite = document.querySelector("#sprite");
const bubble = document.querySelector("#bubble");
const statusLine = document.querySelector("#status");
const gate = document.querySelector("#gate");
const chat = document.querySelector("#chat");
const log = document.querySelector("#log");
const menu = document.querySelector("#menu");
const voiceButton = document.querySelector("#voice");
const voiceNote = document.querySelector("#voice-note");

const state = {
  clips: [],
  poses: [],
  recent: [],
  playing: false,
  sleeping: false,
  drag: null,
  autonomous: true,
};

function say(text, seconds = 3.2) {
  bubble.textContent = text;
  bubble.classList.remove("hidden");
  clearTimeout(say.timer);
  say.timer = setTimeout(() => bubble.classList.add("hidden"), seconds * 1000);
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  if (response.status === 401) {
    gate.classList.remove("hidden");
    throw new Error("需要访问口令");
  }
  return response;
}

async function boot() {
  const session = await fetch("/api/session", { credentials: "same-origin" });
  const sessionBody = await session.json();
  if (sessionBody.password_required && !sessionBody.ok) {
    gate.classList.remove("hidden");
    return;
  }
  const response = await api("/api/clips");
  const body = await response.json();
  state.clips = body.clips || [];
  state.poses = body.sleep_poses || [];
  statusLine.textContent = "团子自己会找事做";
  pet.classList.add("awake");
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/sw.js").catch(() => {});
  }
  setupVoice();
  autonomous();
  pollReminders();
}

document.querySelector("#gate-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const password = document.querySelector("#password").value;
  const response = await fetch("/api/session", {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ password }),
  });
  if (!response.ok) {
    document.querySelector("#gate-error").textContent = "口令不对";
    return;
  }
  gate.classList.add("hidden");
  boot();
});

function clipById(id) {
  return state.clips.find((clip) => clip.id === id && clip.available && clip.frames.length);
}

function showFrame(url) {
  sprite.src = url;
}

async function playClip(id) {
  if (id === "butterfly") {
    say("发现蝴蝶啦");
    return playClip("pounce");
  }
  if (id === "tail" || id === "tilt" || id === "hop") {
    say(id === "hop" ? "喵！" : "嗯？");
    pet.animate([{ transform: "translateY(0)" }, { transform: "translateY(-14px)" }, { transform: "translateY(0)" }], { duration: 700 });
    return;
  }
  const clip = clipById(id);
  if (!clip) {
    return;
  }
  state.playing = true;
  pet.classList.remove("awake");
  const started = performance.now();
  const total = clip.frames.length * clip.duration_ms;
  let frame = -1;
  while (performance.now() - started < total && !state.sleeping) {
    const index = Math.min(clip.frames.length - 1, Math.floor((performance.now() - started) / clip.duration_ms));
    if (index !== frame) {
      frame = index;
      showFrame(clip.frames[index]);
      if ((id === "walk" || id === "run") && clip.stride_pixels && !String(pet.style.left).endsWith("px")) {
        const direction = state.recent.length % 2 ? 1 : -1;
        const current = parseFloat(pet.style.left || "58");
        pet.style.left = Math.max(8, Math.min(78, current + direction * 0.35)) + "%";
      }
    }
    await wait(Math.min(clip.duration_ms, 40));
  }
  state.playing = false;
  if (!state.sleeping) {
    pet.classList.add("awake");
  }
}

function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function autonomous() {
  while (state.autonomous) {
    if (state.sleeping || state.playing || !state.clips.length) {
      await wait(700);
      continue;
    }
    try {
      const response = await api("/api/activity/next", {
        method: "POST",
        body: JSON.stringify({ recent: state.recent.slice(-6) }),
      });
      const step = await response.json();
      state.recent.push(step.clip);
      if (step.clip === "bed") {
        startSleep();
      } else {
        await playClip(step.clip);
        await wait(step.pause_ms || 1200);
      }
    } catch (error) {
      statusLine.textContent = error.message;
      await wait(2000);
    }
  }
}

function startSleep() {
  state.sleeping = true;
  pet.classList.remove("awake");
  pet.classList.add("sleep");
  const nest = clipById("nest-breath");
  if (nest) {
    playNest(nest);
    return;
  }
  const pose = state.poses[Math.floor(Math.random() * state.poses.length)];
  if (pose) {
    showFrame(pose.image);
  }
  say("团子安静陪着你…", 4);
  statusLine.textContent = "休息一下";
}

async function playNest(clip) {
  say("团子在窝里呼吸", 3);
  while (state.sleeping) {
    for (const frame of clip.frames) {
      if (!state.sleeping) {
        return;
      }
      showFrame(frame);
      await wait(clip.duration_ms);
    }
  }
}

function wake() {
  state.sleeping = false;
  pet.classList.remove("sleep");
  pet.classList.add("awake");
  showFrame("/media/sprites/tuanzi-approved.png");
  say("醒啦，继续陪你");
  statusLine.textContent = "团子自己会找事做";
}

pet.addEventListener("pointerdown", (event) => {
  state.drag = { x: event.clientX, y: event.clientY, left: pet.offsetLeft, top: pet.offsetTop, moved: false };
  pet.setPointerCapture(event.pointerId);
});

pet.addEventListener("pointermove", (event) => {
  if (!state.drag) {
    return;
  }
  const dx = event.clientX - state.drag.x;
  const dy = event.clientY - state.drag.y;
  if (Math.abs(dx) + Math.abs(dy) > 8) {
    state.drag.moved = true;
  }
  if (state.drag.moved) {
    pet.style.left = Math.max(0, state.drag.left + dx) + "px";
    pet.style.top = Math.max(0, state.drag.top + dy) + "px";
    pet.style.bottom = "auto";
  }
});

pet.addEventListener("pointerup", () => {
  if (state.drag && !state.drag.moved) {
    say(["喵～ 好舒服", "呼噜呼噜…", "蹭蹭你的手～"][state.recent.length % 3]);
    playClip("nuzzle");
  }
  state.drag = null;
});

pet.addEventListener("dblclick", (event) => {
  event.preventDefault();
  openChat();
});

document.querySelector("#menu-button").addEventListener("click", () => {
  menu.classList.toggle("hidden");
});

menu.addEventListener("click", (event) => {
  const act = event.target.dataset.act;
  if (!act) {
    return;
  }
  menu.classList.add("hidden");
  if (act === "chat") {
    openChat();
  } else if (act === "sleep") {
    startSleep();
  } else if (act === "wake") {
    wake();
  } else if (act === "groom") {
    playClip("groom");
  } else if (act === "butterfly") {
    playClip("butterfly");
  }
});

function openChat() {
  chat.classList.remove("hidden");
  document.querySelector("#line").focus();
}

document.querySelector("#chat-close").addEventListener("click", () => chat.classList.add("hidden"));

document.querySelector("#composer").addEventListener("submit", (event) => {
  event.preventDefault();
  const line = document.querySelector("#line");
  const text = line.value.trim();
  if (!text) {
    return;
  }
  line.value = "";
  sendChat(text);
});

function append(role, text) {
  const node = document.createElement("p");
  node.className = "line " + role;
  node.textContent = text;
  log.append(node);
  log.scrollTop = log.scrollHeight;
  return node;
}

async function sendChat(text) {
  append("user", text);
  const reply = append("assistant", "");
  const history = [...log.querySelectorAll(".line")].slice(-8).map((node) => ({
    role: node.classList.contains("user") ? "user" : "assistant",
    content: node.textContent,
  }));
  const response = await api("/api/chat", { method: "POST", body: JSON.stringify({ messages: history }) });
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let spoken = "";
  while (true) {
    const chunk = await reader.read();
    if (chunk.done) {
      break;
    }
    buffer += decoder.decode(chunk.value, { stream: true });
    const parts = buffer.split("\n\n");
    buffer = parts.pop();
    for (const part of parts) {
      const line = part.split("\n").find((item) => item.startsWith("data:"));
      if (!line) {
        continue;
      }
      const payload = JSON.parse(line.slice(5));
      if (payload.delta) {
        spoken += payload.delta;
        reply.textContent = spoken;
      }
      if (payload.action) {
        applyClientAction(payload.action);
      }
    }
  }
  if (spoken && window.isSecureContext && window.speechSynthesis) {
    window.speechSynthesis.speak(new SpeechSynthesisUtterance(spoken.slice(0, 120)));
  }
}

function applyClientAction(action) {
  if (!action || !action.ok) {
    return;
  }
  if (action.client_effect === "sleep" || action.name === "sleep") {
    startSleep();
  } else if (action.name === "groom") {
    playClip("groom");
  } else if (action.name === "butterfly") {
    playClip("butterfly");
  } else if (action.name === "remind") {
    say(action.text || "记住啦");
  }
}

function setupVoice() {
  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!window.isSecureContext || !Recognition) {
    voiceButton.disabled = true;
    voiceNote.textContent = window.isSecureContext ? "这台浏览器没有语音识别。" : "语音只在 HTTPS（或本机安全页面）里打开。";
    return;
  }
  voiceNote.textContent = "点「说话」，团子听你一句。";
  const recognition = new Recognition();
  recognition.lang = "zh-CN";
  recognition.onresult = (event) => {
    const text = event.results[0][0].transcript;
    if (text) {
      sendChat(text);
    }
  };
  voiceButton.addEventListener("click", () => recognition.start());
}

async function pollReminders() {
  while (true) {
    await wait(15000);
    try {
      const response = await api("/api/reminders");
      const body = await response.json();
      for (const item of body.due || []) {
        say(item.text, 5);
      }
    } catch (_error) {
      /* The next poll retries. */
    }
  }
}

boot();
