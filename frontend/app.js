/** Avatar：WebRTC 音视频（TURN 中继） */
let avatarPc = null;
let avatarStreamConnected = false;
let avatarEnabled = false;
let avatarIceServers = [{ urls: "stun:stun.l.google.com:19302" }];
let avatarIceTransportPolicy = "all";
let avatarWebRTCPumpActive = false;
const avatarVideo = document.getElementById("avatarVideo");
const avatarCanvas = document.getElementById("avatarCanvas");
const avatarFrame = document.getElementById("avatarFrame");
const avatarStatus = document.getElementById("avatarStatus");
const avatarFpsEl = document.getElementById("avatarFps");
let avatarCanvasCtx = avatarCanvas ? avatarCanvas.getContext("2d") : null;
let avatarFpsMonitorActive = false;
let avatarFpsStatsTimer = null;
let avatarFpsLastDecoded = 0;
let avatarFpsLastStatsAt = 0;

function setAvatarStatus(text) {
  if (avatarStatus) avatarStatus.textContent = text;
}

/** aiortc 有时不触发 ontrack，从 receivers 绑定 MediaStream */
function attachAvatarWebRTCStream(pc) {
  if (!avatarVideo || !pc) return false;
  const tracks = pc.getReceivers().map((r) => r.track).filter(Boolean);
  if (!tracks.length) return false;

  const stream = new MediaStream(tracks);
  avatarVideo.srcObject = stream;
  avatarVideo.hidden = false;
  if (avatarFrame) avatarFrame.hidden = true;
  if (avatarCanvas) avatarCanvas.hidden = true;
  avatarStreamConnected = true;
  setAvatarStatus("Live2D 视频流已连接 (WebRTC)");
  startAvatarWebRTCPump();
  startAvatarFpsMonitor();
  resumeAvatarWebRTCPlayback();
  return true;
}

function resumeAvatarWebRTCPlayback() {
  if (!avatarVideo || !avatarVideo.srcObject) return;
  avatarVideo.muted = false;
  avatarVideo.play().catch(() => {
    avatarVideo.muted = true;
    avatarVideo.play().catch(() => {});
  });
}

function scheduleAttachAvatarWebRTCStream(pc) {
  if (!pc) return;
  const tryAttach = () => attachAvatarWebRTCStream(pc);
  tryAttach();
  window.setTimeout(tryAttach, 300);
  window.setTimeout(tryAttach, 1500);
}

function stopAvatarWebRTCPump() {
  avatarWebRTCPumpActive = false;
  stopAvatarFpsMonitor();
}

function setAvatarFpsDisplay(fps) {
  if (!avatarFpsEl) return;
  if (!Number.isFinite(fps) || fps <= 0) {
    avatarFpsEl.hidden = true;
    return;
  }
  avatarFpsEl.hidden = false;
  avatarFpsEl.textContent = `解码 ${fps.toFixed(1)} fps`;
}

function stopAvatarFpsMonitor() {
  avatarFpsMonitorActive = false;
  if (avatarFpsStatsTimer != null) {
    clearTimeout(avatarFpsStatsTimer);
    avatarFpsStatsTimer = null;
  }
  avatarFpsLastDecoded = -1;
  avatarFpsLastStatsAt = 0;
  if (avatarFpsEl) avatarFpsEl.hidden = true;
}

/** WebRTC 解码帧率（framesDecoded 差分；不用 RVFC，低帧率流上易虚高到 ~60） */
function startAvatarFpsMonitor() {
  if (avatarFpsMonitorActive || !avatarVideo) return;
  avatarFpsMonitorActive = true;
  avatarFpsLastDecoded = -1;
  avatarFpsLastStatsAt = 0;

  const pollStats = async () => {
    if (!avatarFpsMonitorActive) return;
    if (!avatarPc) {
      avatarFpsStatsTimer = window.setTimeout(pollStats, 500);
      return;
    }
    const receiver = avatarPc
      .getReceivers()
      .find((r) => r.track && r.track.kind === "video");
    if (!receiver) {
      avatarFpsStatsTimer = window.setTimeout(pollStats, 500);
      return;
    }
    try {
      const stats = await receiver.getStats();
      let inbound = null;
      stats.forEach((report) => {
        if (report.type !== "inbound-rtp" || report.kind !== "video") return;
        const decoded = report.framesDecoded ?? 0;
        if (!inbound || decoded > (inbound.framesDecoded ?? 0)) inbound = report;
      });
      if (inbound && typeof inbound.framesDecoded === "number") {
        const decoded = inbound.framesDecoded;
        const now = performance.now();
        if (avatarFpsLastDecoded >= 0 && avatarFpsLastStatsAt > 0) {
          const dt = (now - avatarFpsLastStatsAt) / 1000;
          const df = decoded - avatarFpsLastDecoded;
          if (dt >= 0.4 && df >= 0) setAvatarFpsDisplay(df / dt);
        }
        avatarFpsLastDecoded = decoded;
        avatarFpsLastStatsAt = now;
      }
    } catch {
      /* ignore */
    }
    avatarFpsStatsTimer = window.setTimeout(pollStats, 500);
  };
  pollStats();
}

/** WebRTC 解码后画到 canvas（video 保留用于出声） */
function drawAvatarWebRTCFrame() {
  if (!avatarCanvas || !avatarCanvasCtx || !avatarVideo) return;
  const w = avatarVideo.videoWidth;
  const h = avatarVideo.videoHeight;
  if (!w || !h) return;
  if (avatarCanvas.width !== w || avatarCanvas.height !== h) {
    avatarCanvas.width = w;
    avatarCanvas.height = h;
  }
  avatarCanvasCtx.drawImage(avatarVideo, 0, 0, w, h);
  avatarCanvas.hidden = false;
  if (avatarFrame) avatarFrame.hidden = true;
  avatarVideo.hidden = false;
  avatarVideo.style.opacity = "0";
  avatarVideo.style.pointerEvents = "none";
}

function startAvatarWebRTCPump() {
  if (avatarWebRTCPumpActive || !avatarVideo || !avatarCanvas) return;
  avatarWebRTCPumpActive = true;
  const pump = () => {
    if (!avatarWebRTCPumpActive) return;
    if (avatarVideo.srcObject && avatarVideo.readyState >= 2) {
      drawAvatarWebRTCFrame();
    }
    requestAnimationFrame(pump);
  };
  requestAnimationFrame(pump);
}

function closeAvatarStreams() {
  stopAvatarWebRTCPump();
  avatarStreamConnected = false;
  if (avatarVideo) {
    avatarVideo.pause();
    avatarVideo.srcObject = null;
    avatarVideo.hidden = true;
    avatarVideo.style.opacity = "";
    avatarVideo.style.pointerEvents = "";
  }
  if (avatarCanvas && avatarCanvasCtx) {
    avatarCanvasCtx.clearRect(0, 0, avatarCanvas.width, avatarCanvas.height);
    avatarCanvas.hidden = true;
  }
  if (avatarPc) {
    avatarPc.close();
    avatarPc = null;
  }
  setAvatarStatus("视频流未连接");
}

function startAvatarVideo() {
  if (!avatarEnabled) return;
  startAvatarWebRTC().catch((e) => {
    setAvatarStatus(`WebRTC: ${e.message}`);
  });
}

async function waitIceGathering(pc) {
  if (pc.iceGatheringState === "complete") return;
  await new Promise((resolve) => {
    const timer = setTimeout(resolve, 8000);
    pc.addEventListener("icegatheringstatechange", () => {
      if (pc.iceGatheringState === "complete") {
        clearTimeout(timer);
        resolve();
      }
    });
  });
}

async function startAvatarWebRTC() {
  if (!avatarEnabled || avatarPc) return;
  if (typeof RTCPeerConnection === "undefined") {
    setAvatarStatus("浏览器不支持 WebRTC");
    return;
  }
  setAvatarStatus("正在连接视频流…");
  const rtcConfig = { iceServers: avatarIceServers };
  if (avatarIceTransportPolicy === "relay") {
    rtcConfig.iceTransportPolicy = "relay";
  }
  avatarPc = new RTCPeerConnection(rtcConfig);
  avatarPc.ontrack = () => {
    attachAvatarWebRTCStream(avatarPc);
  };
  avatarPc.onicecandidate = (ev) => {
    if (ev.candidate) {
      sendJson({ type: "webrtc_ice", candidate: ev.candidate.toJSON() });
    }
  };
  avatarPc.onconnectionstatechange = () => {
    const st = avatarPc?.connectionState;
    if (st === "connected") {
      scheduleAttachAvatarWebRTCStream(avatarPc);
    } else if (st === "failed") {
      avatarStreamConnected = false;
      setAvatarStatus("WebRTC 连接失败");
    } else if (st === "closed" || st === "disconnected") {
      avatarStreamConnected = false;
      setAvatarStatus(`视频流 ${st || "断开"}`);
    }
  };
  avatarPc.addTransceiver("video", { direction: "recvonly" });
  avatarPc.addTransceiver("audio", { direction: "recvonly" });
  const offer = await avatarPc.createOffer();
  await avatarPc.setLocalDescription(offer);
  await waitIceGathering(avatarPc);
  sendJson({
    type: "webrtc_offer",
    sdp: avatarPc.localDescription.sdp,
  });
}

function closeAvatarWebRTC() {
  stopAvatarWebRTCPump();
  avatarStreamConnected = false;
  if (avatarVideo) {
    avatarVideo.pause();
    avatarVideo.srcObject = null;
  }
  if (avatarPc) {
    avatarPc.close();
    avatarPc = null;
  }
}

const STAGE_LABELS = {
  listening: "聆听中 — 请直接说话",
  thinking: "思考中 — 正在生成回复",
  speaking: "回应中 — 正在播放语音",
};

const TARGET_SR = 16000;
const userId = localStorage.getItem("vv_user_id");
if (!userId) {
  location.href = "/login.html";
}

const wsUrl = `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`;
let ws = null;
let authed = false;
let listeningActive = false;
let listenPaused = false;
let audioStream = null;
let audioContext = null;
let scriptProcessor = null;
let micSource = null;
let vadEnabled = false;
let audioQueue = [];
let isPlaying = false;
/** 每次打断递增，用于丢弃打断前已在途的 TTS 分片 */
let playbackGeneration = 0;
/** 与 playbackGeneration 配合，取消尚未完成的 play() */
let activePlayId = 0;
/** 当前正在播放的 blob URL（stop 时需单独 revoke） */
let currentPlayUrl = null;
const ttsPlayer = document.getElementById("ttsPlayer");
let currentStage = "listening";
/** 与服务端 turn_id 对齐，丢弃已打断回合的迟到 utterance */
let serverTurnId = 0;
/** 当前轮助手回复气泡（按句追加，与 TTS 同步） */
let assistantTurnEl = null;

const statusText = document.getElementById("statusText");
const micBadge = document.getElementById("micBadge");
const liveText = document.getElementById("liveText");
const chatLog = document.getElementById("chatLog");
const btnToggleListen = document.getElementById("btnToggleListen");
const btnInterrupt = document.getElementById("btnInterrupt");
const btnReset = document.getElementById("btnReset");
const userBadge = document.getElementById("userBadge");
const pfProfile = document.getElementById("pfProfile");
const pfTopic = document.getElementById("pfTopic");
const pfInterests = document.getElementById("pfInterests");

userBadge.textContent = `用户: ${userId}`;

function setProfileForm(form) {
  if (!form) return;
  pfProfile.textContent = form.user_profile || "—";
  pfTopic.textContent = form.current_topic || "—";
  const list = form.historical_interests || [];
  pfInterests.textContent = list.length ? list.map((x) => `• ${x}`).join("\n") : "—";
}

function setStage(stage) {
  currentStage = stage;
  document.querySelectorAll(".stage-indicator").forEach((el) => {
    el.classList.toggle("active", el.dataset.stage === stage);
  });
  statusText.textContent = STAGE_LABELS[stage] || stage;
  btnInterrupt.disabled = stage !== "speaking" && stage !== "thinking";
}

function appendMsg(role, text) {
  const el = document.createElement("div");
  el.className = `msg ${role}`;
  el.textContent = text;
  chatLog.appendChild(el);
  chatLog.scrollTop = chatLog.scrollHeight;
  return el;
}

function sendJson(obj) {
  if (ws?.readyState === WebSocket.OPEN) ws.send(JSON.stringify(obj));
}

function downsample(buffer, fromRate, toRate) {
  if (fromRate === toRate) return buffer;
  const ratio = fromRate / toRate;
  const outLen = Math.round(buffer.length / ratio);
  const out = new Float32Array(outLen);
  for (let i = 0; i < outLen; i++) {
    out[i] = buffer[Math.min(Math.floor(i * ratio), buffer.length - 1)];
  }
  return out;
}

async function startListening() {
  audioStream = await navigator.mediaDevices.getUserMedia({
    audio: {
      echoCancellation: true,
      noiseSuppression: true,
      autoGainControl: true,
    },
  });
  audioContext = new AudioContext();
  micSource = audioContext.createMediaStreamSource(audioStream);
  scriptProcessor = audioContext.createScriptProcessor(4096, 1, 1);
  scriptProcessor.onaudioprocess = (e) => {
    if (!listeningActive || listenPaused || !authed || !vadEnabled) return;
    const input = e.inputBuffer.getChannelData(0);
    const samples = downsample(input, audioContext.sampleRate, TARGET_SR);
    sendJson({ type: "raw_audio", audio: Array.from(samples) });
  };
  micSource.connect(scriptProcessor);
  scriptProcessor.connect(audioContext.destination);
  micBadge.hidden = false;
  liveText.textContent = "Silero VAD 聆听中（服务端切段）…";
}

function stopMicTracks() {
  scriptProcessor?.disconnect();
  micSource?.disconnect();
  scriptProcessor = null;
  micSource = null;
  audioStream?.getTracks().forEach((t) => t.stop());
  audioStream = null;
  audioContext?.close().catch(() => {});
  audioContext = null;
  micBadge.hidden = true;
}

function pauseListening() {
  listenPaused = true;
  liveText.textContent = "已暂停发送麦克风";
}

function resumeListening() {
  listenPaused = false;
  if (!audioStream) {
    startListening().catch((e) => appendMsg("system", `麦克风错误: ${e.message}`));
  } else {
    liveText.textContent = "Silero VAD 聆听中（服务端切段）…";
  }
}

function acceptTurnMsg(msg) {
  return msg.turn_id == null || msg.turn_id === serverTurnId;
}

function syncTurnId(msg) {
  if (msg.turn_id != null) serverTurnId = msg.turn_id;
}

function handleServerMessage(msg) {
  switch (msg.type) {
    case "await_auth":
      sendJson({ type: "auth", user_id: userId });
      break;
    case "auth_ok":
      authed = true;
      vadEnabled = !!msg.vad_enabled;
      avatarEnabled = !!msg.avatar_enabled;
      if (Array.isArray(msg.ice_servers) && msg.ice_servers.length) {
        avatarIceServers = msg.ice_servers;
      }
      avatarIceTransportPolicy = msg.ice_transport_policy || "all";
      setStage(msg.stage || "listening");
      setProfileForm(msg.profile_form);
      btnToggleListen.disabled = false;
      appendMsg(
        "system",
        `已登录 ${msg.user_id}${vadEnabled ? "（Silero VAD）" : "（VAD 未启用）"}`
      );
      if (avatarEnabled && msg.avatar_webrtc) {
        startAvatarVideo();
      } else if (avatarEnabled) {
        setAvatarStatus("Avatar 已启用（WebRTC 未开）");
      }
      break;
    case "webrtc_answer":
      if (!avatarPc) break;
      avatarPc
        .setRemoteDescription({ type: "answer", sdp: msg.sdp })
        .then(() => {
          setAvatarStatus("信令完成，等待画面…");
          scheduleAttachAvatarWebRTCStream(avatarPc);
        })
        .catch((e) => setAvatarStatus(`信令失败: ${e.message}`));
      break;
    case "webrtc_ice":
      if (!avatarPc || !msg.candidate) break;
      avatarPc.addIceCandidate(new RTCIceCandidate(msg.candidate)).catch(() => {});
      break;
    case "stage":
      // 仅更新指示器；勿在 speaking→listening 时 stopPlayback（服务端会先 turn_done，
      // 此时队列里可能还有未播完的句，误清会导致「只播第一句」）
      setStage(msg.stage);
      break;
    case "stop_audio":
      syncTurnId(msg);
      stopPlayback();
      assistantTurnEl = null;
      break;
    case "vad":
      if (msg.event === "speech_start") {
        liveText.textContent = "检测到说话…";
        // 不依赖 stage：只要 TTS 在播/排队就立刻停（避免 stage 已是 listening 时漏停当句）
        if (isPlaying || audioQueue.length > 0 || (ttsPlayer && !ttsPlayer.paused)) {
          stopPlayback();
          assistantTurnEl = null;
        }
      } else if (msg.event === "speech_end") {
        liveText.textContent = "语音结束，识别中…";
      } else if (msg.event === "filtered") {
        liveText.textContent = "已忽略背景音";
      }
      break;
    case "control":
      if (msg.text === "interrupt") {
        stopPlayback();
        assistantTurnEl = null;
        liveText.textContent = "语音打断";
      }
      break;
    case "user_text":
      syncTurnId(msg);
      assistantTurnEl = null;
      appendMsg("user", msg.text);
      liveText.textContent = msg.text;
      setStage("thinking");
      break;
    case "assistant_utterance":
      if (!acceptTurnMsg(msg)) break;
      syncTurnId(msg);
      if (msg.text) {
        if (!assistantTurnEl) {
          assistantTurnEl = appendMsg("assistant", msg.text);
        } else {
          assistantTurnEl.textContent += msg.text;
        }
        chatLog.scrollTop = chatLog.scrollHeight;
        liveText.textContent = msg.text;
      }
      if (msg.data) {
        if (avatarStreamConnected) {
          /* WebRTC 已出声 */
        } else {
          enqueueAudio(msg.data, msg.format || "mp3");
        }
      }
      break;
    case "assistant_final":
      if (!acceptTurnMsg(msg)) break;
      syncTurnId(msg);
      assistantTurnEl = null;
      if (msg.avatar) appendMsg("system", `[Live2D] ${JSON.stringify(msg.avatar)}`);
      if (msg.profile_form) setProfileForm(msg.profile_form);
      break;
    case "turn_done":
      syncTurnId(msg);
      finishTurnAndResumeListen();
      break;
    case "interrupted":
    case "reset_ok":
      syncTurnId(msg);
      setStage("listening");
      stopPlayback();
      assistantTurnEl = null;
      if (listeningActive && !listenPaused && authed) resumeListening();
      break;
    case "error":
      appendMsg("system", msg.message);
      if (msg.message && String(msg.message).includes("Avatar")) {
        setAvatarStatus(`Avatar: ${msg.message}`);
      }
      setStage("listening");
      stopPlayback();
      if (listeningActive && !listenPaused && authed) resumeListening();
      break;
  }
}

function detachTtsHandlers() {
  ttsPlayer.onended = null;
  ttsPlayer.onerror = null;
}

function enqueueAudio(b64, format) {
  const gen = playbackGeneration;
  const bin = atob(b64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  const url = URL.createObjectURL(new Blob([bytes], { type: `audio/${format}` }));
  audioQueue.push({ url, gen });
  playNext();
}

function stopPlayback() {
  playbackGeneration += 1;
  activePlayId += 1;
  detachTtsHandlers();
  audioQueue.forEach((item) => URL.revokeObjectURL(item.url));
  audioQueue = [];
  isPlaying = false;
  if (currentPlayUrl) {
    URL.revokeObjectURL(currentPlayUrl);
    currentPlayUrl = null;
  }
  if (!ttsPlayer) return;
  try {
    ttsPlayer.pause();
    ttsPlayer.currentTime = 0;
    ttsPlayer.removeAttribute("src");
    ttsPlayer.load();
  } catch (_) {
    /* ignore */
  }
}

function playNext() {
  while (audioQueue.length && audioQueue[0].gen !== playbackGeneration) {
    URL.revokeObjectURL(audioQueue.shift().url);
  }
  if (isPlaying || !audioQueue.length || !ttsPlayer) return;

  const { url, gen } = audioQueue.shift();
  const playId = ++activePlayId;
  isPlaying = true;
  currentPlayUrl = url;

  detachTtsHandlers();
  ttsPlayer.src = url;

  const done = () => {
    detachTtsHandlers();
    if (currentPlayUrl === url) {
      URL.revokeObjectURL(url);
      currentPlayUrl = null;
    } else {
      URL.revokeObjectURL(url);
    }
    isPlaying = false;
    if (!ttsPlayer) return;
    try {
      ttsPlayer.pause();
      ttsPlayer.currentTime = 0;
      ttsPlayer.removeAttribute("src");
      ttsPlayer.load();
    } catch (_) {
      /* ignore */
    }
    if (playId === activePlayId && gen === playbackGeneration) playNext();
  };

  ttsPlayer.onended = done;
  ttsPlayer.onerror = done;

  const playPromise = ttsPlayer.play();
  if (playPromise && typeof playPromise.then === "function") {
    playPromise
      .then(() => {
        if (playId !== activePlayId || gen !== playbackGeneration) {
          detachTtsHandlers();
          if (currentPlayUrl === url) {
            URL.revokeObjectURL(url);
            currentPlayUrl = null;
          } else {
            URL.revokeObjectURL(url);
          }
          try {
            ttsPlayer.pause();
            ttsPlayer.currentTime = 0;
            ttsPlayer.removeAttribute("src");
            ttsPlayer.load();
          } catch (_) {
            /* ignore */
          }
          isPlaying = false;
        }
      })
      .catch(done);
  }
}

function finishTurnAndResumeListen() {
  const wait = () => {
    if (!isPlaying && audioQueue.length === 0) {
      setStage("listening");
      if (listeningActive && !listenPaused && authed) resumeListening();
    } else {
      setTimeout(wait, 150);
    }
  };
  wait();
}

function connect() {
  ws = new WebSocket(wsUrl);
  ws.onopen = () => {
    statusText.textContent = "连接中，正在登录…";
  };
  ws.onclose = () => {
    authed = false;
    listeningActive = false;
    listenPaused = false;
    closeAvatarStreams();
    stopMicTracks();
    btnToggleListen.disabled = true;
    statusText.textContent = "连接已断开";
  };
  ws.onmessage = (e) => {
    if (typeof e.data !== "string") {
      console.warn("收到非 JSON WS 二进制消息，已忽略");
      return;
    }
    handleServerMessage(JSON.parse(e.data));
  };
}

btnToggleListen.addEventListener("click", async () => {
  if (!authed) return;
  resumeAvatarWebRTCPlayback();
  if (!listeningActive) {
    listeningActive = true;
    listenPaused = false;
    btnToggleListen.textContent = "暂停聆听";
    await startListening();
    return;
  }
  listenPaused = !listenPaused;
  if (listenPaused) {
    pauseListening();
    btnToggleListen.textContent = "继续聆听";
    statusText.textContent = "已暂停";
  } else {
    btnToggleListen.textContent = "暂停聆听";
    resumeListening();
  }
});

btnInterrupt.addEventListener("click", () => {
  stopPlayback();
  sendJson({ type: "interrupt" });
});
btnReset.addEventListener("click", () => {
  chatLog.innerHTML = "";
  assistantTurnEl = null;
  sendJson({ type: "reset" });
});
document.getElementById("btnLogout").addEventListener("click", () => {
  localStorage.removeItem("vv_user_id");
  location.href = "/login.html";
});

connect();
