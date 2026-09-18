// Voice conversation. In the default "browser" mode audio never leaves this page:
// capture uses the Web Speech API and playback uses speechSynthesis. Only when the
// server reports stt/tts = "openai" is audio posted to /api/voice/*.
const DjinVoice = (() => {
  const MIN_CHUNK = 40;
  const MAX_CHUNK = 220;
  const BOUNDARY = ".!?…:;";

  const SPEECH_LEVEL = 0.035;
  const SILENCE_MS = 1200;
  const NO_SPEECH_MS = 6000;
  const MAX_UTTERANCE_MS = 30000;
  const MAX_EMPTY_STREAK = 2;

  const ui = {};
  const hooks = { send: () => {}, isBusy: () => false };

  const state = {
    config: null,
    available: false,
    speakEnabled: true,
    handsFree: false,
    listening: false,
    voiceTurn: false,
    turnOpen: false,
    emptyStreak: 0,
  };

  let buffer = "";
  const queue = [];
  let draining = false;
  let synthVoice = null;
  let recognition = null;
  let recorder = null;
  let micStream = null;
  let audioContext = null;
  let monitorTimer = 0;
  let currentAudio = null;
  let abortListening = false;

  // ---------------------------------------------------------------- text -> speech

  function toSpeech(markdown) {
    return markdown
      .replace(/```[\s\S]*?```/g, " code block omitted. ")
      .replace(/`([^`]*)`/g, "$1")
      .replace(/!\[[^\]]*\]\([^)]*\)/g, " ")
      .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
      .replace(/^\s{0,3}#{1,6}\s+/gm, "")
      .replace(/^\s{0,3}>\s?/gm, "")
      .replace(/^\s*\|.*\|\s*$/gm, " ")
      .replace(/^\s*([-*_]\s*){3,}$/gm, " ")
      .replace(/^\s*[-*+]\s+/gm, "")
      .replace(/^\s*\d+[.)]\s+/gm, "")
      .replace(/(\*\*|__|~~|\*|_)/g, "")
      .replace(/<[^>]+>/g, " ")
      .replace(/https?:\/\/\S+/g, " link ")
      .replace(/\s+/g, " ")
      .trim();
  }

  function lastBoundary(text) {
    let best = -1;
    for (let i = 0; i < text.length; i += 1) {
      const char = text[i];
      if (char === "\n") best = i;
      else if (BOUNDARY.includes(char) && /\s/.test(text[i + 1] || "")) best = i;
    }
    return best;
  }

  function takeChunk(force) {
    if (!buffer.trim()) {
      if (force) buffer = "";
      return "";
    }
    // Never read out a code fence that has not closed yet.
    const fences = (buffer.match(/```/g) || []).length;
    if (!force && fences % 2 === 1) return "";

    if (force) {
      const rest = buffer;
      buffer = "";
      return rest;
    }

    const boundary = lastBoundary(buffer);
    if (boundary >= 0 && boundary + 1 >= MIN_CHUNK) {
      const chunk = buffer.slice(0, boundary + 1);
      buffer = buffer.slice(boundary + 1);
      return chunk;
    }
    if (buffer.length < MAX_CHUNK) return "";

    const space = buffer.lastIndexOf(" ", MAX_CHUNK);
    const cut = space > MIN_CHUNK ? space : MAX_CHUNK;
    const chunk = buffer.slice(0, cut);
    buffer = buffer.slice(cut);
    return chunk;
  }

  // ---------------------------------------------------------------- speaking

  function pickSynthVoice() {
    if (!window.speechSynthesis) return;
    const voices = window.speechSynthesis.getVoices();
    if (!voices.length) return;
    const wanted = (state.config.language || "en-US").toLowerCase();
    synthVoice =
      voices.find((v) => v.lang && v.lang.toLowerCase() === wanted) ||
      voices.find((v) => v.lang && v.lang.toLowerCase().startsWith(wanted.slice(0, 2))) ||
      voices[0];
  }

  function speakBrowser(text) {
    return new Promise((resolve) => {
      const utterance = new SpeechSynthesisUtterance(text);
      utterance.lang = state.config.language || "en-US";
      if (synthVoice) utterance.voice = synthVoice;
      utterance.onend = resolve;
      utterance.onerror = resolve;
      window.speechSynthesis.speak(utterance);
    });
  }

  async function speakServer(text) {
    const response = await fetch("/api/voice/speak", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
    if (!response.ok) throw new Error(`speech failed (${response.status})`);

    const url = URL.createObjectURL(await response.blob());
    const audio = new Audio(url);
    currentAudio = audio;
    try {
      await new Promise((resolve) => {
        audio.onended = resolve;
        audio.onerror = resolve;
        audio.play().catch(resolve);
      });
    } finally {
      currentAudio = null;
      URL.revokeObjectURL(url);
    }
  }

  function enqueue(raw) {
    const text = toSpeech(raw);
    if (!text || !state.speakEnabled) return;
    queue.push(text);
    drain();
  }

  async function drain() {
    if (draining) return;
    draining = true;
    while (queue.length && state.speakEnabled) {
      setStatus("speaking", "speaking…");
      const text = queue.shift();
      try {
        if (state.config.tts === "openai") await speakServer(text);
        else await speakBrowser(text);
      } catch {
        /* a failed chunk must not stall the rest of the reply */
      }
    }
    draining = false;
    onIdle();
  }

  function stopSpeaking() {
    queue.length = 0;
    buffer = "";
    if (window.speechSynthesis) window.speechSynthesis.cancel();
    if (currentAudio) {
      currentAudio.pause();
      currentAudio = null;
    }
  }

  function onIdle() {
    if (state.turnOpen || draining || queue.length) return;
    if (state.handsFree && state.voiceTurn && !state.listening && !hooks.isBusy()) {
      startListening();
    } else if (!state.listening) {
      setStatus("idle", "");
    }
  }

  // ---------------------------------------------------------------- listening

  function submitTranscript(text) {
    const spoken = text.trim();
    if (!spoken) {
      state.emptyStreak += 1;
      if (state.handsFree && state.emptyStreak >= MAX_EMPTY_STREAK) {
        setHandsFree(false);
        setStatus("idle", "No speech detected. Hands-free off.");
      } else {
        setStatus("idle", "Did not catch that.");
      }
      onIdle();
      return;
    }
    state.emptyStreak = 0;
    state.voiceTurn = true;
    setStatus("idle", "");
    hooks.send(spoken, true);
  }

  function startBrowserRecognition() {
    const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    let finalText = "";
    let failure = "";

    recognition = new Recognition();
    recognition.lang = state.config.language || "en-US";
    recognition.interimResults = true;
    recognition.continuous = false;
    recognition.maxAlternatives = 1;

    recognition.onresult = (event) => {
      let interim = "";
      for (let i = event.resultIndex; i < event.results.length; i += 1) {
        const result = event.results[i];
        if (result.isFinal) finalText += result[0].transcript;
        else interim += result[0].transcript;
      }
      setStatus("listening", `${finalText}${interim}`.trim() || "listening…");
    };
    recognition.onerror = (event) => {
      failure = event.error || "unknown";
    };
    recognition.onend = () => {
      recognition = null;
      setListening(false);
      if (abortListening) return;
      if (failure && failure !== "no-speech" && failure !== "aborted") {
        setHandsFree(false);
        setStatus("error", micErrorText(failure));
        return;
      }
      submitTranscript(finalText);
    };

    recognition.start();
  }

  function micErrorText(code) {
    if (code === "not-allowed" || code === "service-not-allowed" || code === "NotAllowedError") {
      return "Microphone access was denied. Allow it in the browser and try again.";
    }
    if (code === "NotFoundError") return "No microphone was found.";
    if (code === "audio-capture") return "No microphone was found.";
    if (code === "network") return "Speech recognition could not reach its network service.";
    return `Microphone error: ${code}`;
  }

  function preferredMimeType() {
    const candidates = [
      "audio/webm;codecs=opus",
      "audio/webm",
      "audio/ogg;codecs=opus",
      "audio/mp4",
    ];
    return candidates.find((type) => window.MediaRecorder.isTypeSupported(type)) || "";
  }

  function stopMonitor() {
    if (monitorTimer) clearInterval(monitorTimer);
    monitorTimer = 0;
    if (audioContext) {
      audioContext.close().catch(() => {});
      audioContext = null;
    }
  }

  function monitorSilence(stream, onDone) {
    const Context = window.AudioContext || window.webkitAudioContext;
    if (!Context) return;

    audioContext = new Context();
    const analyser = audioContext.createAnalyser();
    analyser.fftSize = 1024;
    audioContext.createMediaStreamSource(stream).connect(analyser);

    const samples = new Uint8Array(analyser.fftSize);
    const startedAt = performance.now();
    let lastLoud = startedAt;
    let heardSpeech = false;

    monitorTimer = setInterval(() => {
      analyser.getByteTimeDomainData(samples);
      let sum = 0;
      for (let i = 0; i < samples.length; i += 1) {
        const value = (samples[i] - 128) / 128;
        sum += value * value;
      }
      const level = Math.sqrt(sum / samples.length);
      const now = performance.now();
      if (level > SPEECH_LEVEL) {
        lastLoud = now;
        heardSpeech = true;
      }
      const elapsed = now - startedAt;
      const quietLongEnough = heardSpeech && now - lastLoud > SILENCE_MS;
      if (quietLongEnough || (!heardSpeech && elapsed > NO_SPEECH_MS) || elapsed > MAX_UTTERANCE_MS) {
        stopMonitor();
        onDone();
      }
    }, 100);
  }

  function releaseMic() {
    stopMonitor();
    if (micStream) {
      micStream.getTracks().forEach((track) => track.stop());
      micStream = null;
    }
    recorder = null;
  }

  async function transcribeBlob(blob) {
    if (blob.size < 2000) {
      submitTranscript("");
      return;
    }
    setStatus("working", "transcribing…");
    const body = new FormData();
    body.append("audio", blob, "speech.webm");
    body.append("language", state.config.language || "en-US");
    try {
      const response = await fetch("/api/voice/transcribe", { method: "POST", body });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || `transcription failed (${response.status})`);
      submitTranscript(data.text || "");
    } catch (error) {
      setHandsFree(false);
      setStatus("error", error.message);
    }
  }

  async function startRecording() {
    micStream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true },
    });
    const mimeType = preferredMimeType();
    recorder = new MediaRecorder(micStream, mimeType ? { mimeType } : undefined);
    const chunks = [];

    recorder.ondataavailable = (event) => {
      if (event.data && event.data.size) chunks.push(event.data);
    };
    recorder.onstop = () => {
      const blob = new Blob(chunks, { type: recorder.mimeType || "audio/webm" });
      releaseMic();
      setListening(false);
      if (!abortListening) transcribeBlob(blob);
    };

    recorder.start();
    monitorSilence(micStream, () => {
      if (recorder && recorder.state === "recording") recorder.stop();
    });
  }

  async function startListening() {
    if (state.listening || !state.available) return;
    abortListening = false;
    stopSpeaking();
    setListening(true);
    setStatus("listening", "listening…");
    try {
      if (state.config.stt === "openai") await startRecording();
      else startBrowserRecognition();
    } catch (error) {
      releaseMic();
      setListening(false);
      setHandsFree(false);
      setStatus("error", micErrorText(error.name || error.message));
    }
  }

  function stopListening(discard) {
    abortListening = Boolean(discard);
    if (discard) setStatus("idle", "");
    if (recognition) {
      if (discard) recognition.abort();
      else recognition.stop();
    }
    if (recorder && recorder.state === "recording") recorder.stop();
    else if (discard) releaseMic();
  }

  // ---------------------------------------------------------------- ui

  function setStatus(kind, text) {
    if (!ui.status) return;
    ui.status.textContent = text || "";
    ui.status.className = `voice-status ${kind}`;
  }

  function setListening(value) {
    state.listening = value;
    if (!ui.mic) return;
    ui.mic.classList.toggle("active", value);
    ui.mic.setAttribute("aria-pressed", String(value));
    ui.mic.textContent = value ? "Stop" : "Talk";
  }

  function setHandsFree(value) {
    state.handsFree = value;
    if (ui.handsFree) ui.handsFree.checked = value;
    if (!value) state.emptyStreak = 0;
  }

  function bindUi() {
    ui.bar = document.getElementById("voice-bar");
    ui.mic = document.getElementById("mic");
    ui.handsFree = document.getElementById("hands-free");
    ui.speak = document.getElementById("speak-replies");
    ui.status = document.getElementById("voice-status");

    ui.mic.addEventListener("click", () => {
      if (state.listening) stopListening(true);
      else if (!hooks.isBusy()) startListening();
    });

    ui.handsFree.addEventListener("change", () => {
      setHandsFree(ui.handsFree.checked);
      if (state.handsFree && !state.listening && !hooks.isBusy()) startListening();
      else if (!state.handsFree && state.listening) stopListening(true);
    });

    ui.speak.addEventListener("change", () => {
      state.speakEnabled = ui.speak.checked;
      if (!state.speakEnabled) stopSpeaking();
    });

    document.addEventListener("keydown", (event) => {
      if (event.code === "Space" && event.ctrlKey) {
        event.preventDefault();
        ui.mic.click();
      } else if (event.key === "Escape") {
        stopSpeaking();
        if (state.listening) stopListening(true);
        setHandsFree(false);
      }
    });

    ui.bar.classList.remove("hidden");
  }

  function capabilities(config) {
    const hasRecognition = Boolean(window.SpeechRecognition || window.webkitSpeechRecognition);
    const hasRecorder = Boolean(window.MediaRecorder && navigator.mediaDevices);

    if (config.stt === "openai") {
      if (!config.server_stt_ready) return "Server transcription is not configured.";
      if (!hasRecorder) return "This browser cannot record audio.";
    } else if (!hasRecognition) {
      return "This browser has no speech recognition. Set DJIN_STT_PROVIDER=openai to use the server.";
    }

    if (config.tts === "openai" && !config.server_tts_ready) {
      return "Server speech output is not configured.";
    }
    if (config.tts === "browser" && !window.speechSynthesis) {
      return "This browser cannot speak replies.";
    }
    return "";
  }

  // ---------------------------------------------------------------- public

  async function init(callbacks) {
    Object.assign(hooks, callbacks);
    try {
      const response = await fetch("/api/voice/config");
      state.config = await response.json();
    } catch {
      return;
    }
    if (!state.config.enabled) return;

    bindUi();
    const problem = capabilities(state.config);
    if (problem) {
      ui.mic.disabled = true;
      ui.handsFree.disabled = true;
      setStatus("error", problem);
      return;
    }

    state.available = true;
    if (state.config.tts === "browser") {
      pickSynthVoice();
      window.speechSynthesis.addEventListener("voiceschanged", pickSynthVoice);
    }
  }

  function handleEvent(event) {
    switch (event.type) {
      case "start":
        state.turnOpen = true;
        break;
      case "delta":
        if (!state.voiceTurn) break;
        buffer += event.content || "";
        for (let chunk = takeChunk(false); chunk; chunk = takeChunk(false)) enqueue(chunk);
        break;
      case "message_end": {
        if (!state.voiceTurn) break;
        const rest = takeChunk(true);
        if (rest) enqueue(rest);
        break;
      }
      case "pending":
        // Approvals are never granted by voice; read the request out and hand back control.
        if (state.voiceTurn && event.actions && event.actions.length) {
          setHandsFree(false);
          enqueue(`I need your approval to run ${event.actions[0].tool_name}. Please check the screen.`);
        }
        break;
      case "error":
        if (state.voiceTurn) {
          setHandsFree(false);
          stopSpeaking();
          enqueue("Something went wrong. The details are on screen.");
        }
        break;
      default:
        break;
    }
  }

  function turnEnded() {
    state.turnOpen = false;
    if (!state.voiceTurn) return;
    const rest = takeChunk(true);
    if (rest) enqueue(rest);
    onIdle();
  }

  function setVoiceTurn(value) {
    state.voiceTurn = value;
    if (!value) stopSpeaking();
  }

  return {
    init,
    handleEvent,
    turnEnded,
    setVoiceTurn,
    isVoiceTurn: () => state.voiceTurn,
    stopSpeaking,
  };
})();
