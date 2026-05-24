/** Avatar：WebRTC 音视频（TURN 中继） */
let avatarPc = null;
let avatarStreamConnected = false;
let avatarEnabled = false;
let avatarIceServers = [{ urls: "stun:stun.l.google.com:19302" }];
let avatarIceTransportPolicy = "all";
let avatarWebRTCPumpActive = false;
const avatarVideo = document.getElementById("avatarVideo");
const avatarCanvas = document.getElementById("avatarCanvas");
const avatarStatus = document.getElementById("avatarStatus");
const avatarFpsEl = document.getElementById("avatarFps");
let avatarCanvasCtx = avatarCanvas ? avatarCanvas.getContext("2d") : null;
let avatarFpsMonitorActive = false;
let avatarFpsRvfcHandle = null;
let avatarFpsFrameCount = 0;
let avatarFpsWindowStart = 0;
let avatarFpsLastMediaTime = -1;

function setAvatarStatus(text) {
  if (avatarStatus) avatarStatus.textContent = text;
}

/** 启用 Avatar 时需等 WebRTC 画面就绪后才可开始聆听 */
function updateListenButtonState() {
  if (!btnToggleListen) return;
  const videoReady = avatarStreamConnected;
  btnToggleListen.disabled = !authed || !videoReady;
  if (!authed || listeningActive) return;
  if (!videoReady) {
    statusText.textContent = "已连接，等待视频流…";
  } else {
    statusText.textContent = "视频已连接，可开始聆听";
  }
}

/** aiortc 有时不触发 ontrack，从 receivers 绑定 MediaStream */
function attachAvatarWebRTCStream(pc) {
  if (!avatarVideo || !pc) return false;
  const tracks = pc.getReceivers().map((r) => r.track).filter(Boolean);
  if (!tracks.length) return false;

  const stream = new MediaStream(tracks);
  stream.getAudioTracks().forEach((t) => {
    t.enabled = true;
  });
  avatarVideo.srcObject = stream;
  avatarVideo.hidden = false;
  if (avatarCanvas) avatarCanvas.hidden = true;
  avatarStreamConnected = true;
  setAvatarStatus("Live2D 视频流已连接 (WebRTC)");
  updateListenButtonState();
  startAvatarWebRTCPump();
  startAvatarFpsMonitor();
  resumeAvatarWebRTCPlayback();
  return true;
}

function resumeAvatarWebRTCPlayback() {
  if (!avatarVideo || !avatarVideo.srcObject) return;
  const audioTracks = avatarVideo.srcObject.getAudioTracks?.() || [];
  if (!audioTracks.length) {
    setAvatarStatus("WebRTC: 等待音频轨…");
    return;
  }
  avatarVideo.muted = false;
  avatarVideo.volume = 1;
  avatarVideo.play().catch(() => {
    setAvatarStatus("WebRTC: 点击「开始聆听」以启用声音");
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
  avatarFpsEl.textContent = `画面 ${fps.toFixed(1)} fps`;
}

function stopAvatarFpsMonitor() {
  avatarFpsMonitorActive = false;
  if (avatarVideo && avatarFpsRvfcHandle != null && avatarVideo.cancelVideoFrameCallback) {
    try {
      avatarVideo.cancelVideoFrameCallback(avatarFpsRvfcHandle);
    } catch {
      /* ignore */
    }
  }
  avatarFpsRvfcHandle = null;
  avatarFpsFrameCount = 0;
  avatarFpsWindowStart = 0;
  avatarFpsLastMediaTime = -1;
  if (avatarFpsEl) avatarFpsEl.hidden = true;
}

/** 画面更新帧率：RVFC + mediaTime 去重（避免重复解码帧与显示器刷新虚高） */
function startAvatarFpsMonitor() {
  if (avatarFpsMonitorActive || !avatarVideo) return;
  if (typeof avatarVideo.requestVideoFrameCallback !== "function") return;
  avatarFpsMonitorActive = true;
  avatarFpsFrameCount = 0;
  avatarFpsWindowStart = 0;
  avatarFpsLastMediaTime = -1;

  const onVideoFrame = (_now, metadata) => {
    if (!avatarFpsMonitorActive) return;
    const mt = metadata?.mediaTime;
    if (typeof mt === "number" && mt !== avatarFpsLastMediaTime) {
      avatarFpsLastMediaTime = mt;
      const t = performance.now();
      if (!avatarFpsWindowStart) avatarFpsWindowStart = t;
      avatarFpsFrameCount += 1;
      const dt = (t - avatarFpsWindowStart) / 1000;
      if (dt >= 0.5) {
        setAvatarFpsDisplay(avatarFpsFrameCount / dt);
        avatarFpsFrameCount = 0;
        avatarFpsWindowStart = t;
      }
    }
    avatarFpsRvfcHandle = avatarVideo.requestVideoFrameCallback(onVideoFrame);
  };
  avatarFpsRvfcHandle = avatarVideo.requestVideoFrameCallback(onVideoFrame);
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
  updateListenButtonState();
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
  if (avatarPc) return;
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
    if (attachAvatarWebRTCStream(avatarPc)) {
      resumeAvatarWebRTCPlayback();
    }
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
      updateListenButtonState();
      setAvatarStatus("WebRTC 连接失败");
    } else if (st === "closed" || st === "disconnected") {
      avatarStreamConnected = false;
      updateListenButtonState();
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

const TARGET_SR = 16000;
const userId = localStorage.getItem("vv_user_id");
if (!userId) {
  location.href = "/login.html";
}

const wsUrl = window.vvcGatewayWsUrl();
let ws = null;
let authed = false;
let listeningActive = false;
let listenPaused = false;
let audioStream = null;
let audioContext = null;
let scriptProcessor = null;
let micSource = null;
let vadEnabled = false;
/** 与服务端 turn_id 对齐，丢弃已打断回合的迟到 utterance */
let serverTurnId = 0;
/** 当前轮助手回复气泡（按句追加，与 TTS 同步） */
let assistantTurnEl = null;

const statusText = document.getElementById("statusText");
const micBadge = document.getElementById("micBadge");
const liveText = document.getElementById("liveText");
const chatLog = document.getElementById("chatLog");
const btnToggleListen = document.getElementById("btnToggleListen");
const btnReset = document.getElementById("btnReset");
const userBadge = document.getElementById("userBadge");

if (userBadge && userId) userBadge.textContent = `用户: ${userId}`;

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
  sendJson({ type: "mic_state", enabled: false });
  liveText.textContent = "已暂停发送麦克风";
}

function resumeListening() {
  listenPaused = false;
  sendJson({ type: "mic_state", enabled: true });
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
      updateListenButtonState();
      if (!avatarEnabled) {
        appendMsg("system", "虚拟人未就绪，请检查 Core Playwright 配置");
        statusText.textContent = "Avatar 不可用";
        break;
      }
      appendMsg(
        "system",
        `已登录 ${msg.user_id}${vadEnabled ? "（Silero VAD）" : "（VAD 未启用）"}`
      );
      if (msg.avatar_webrtc) {
        startAvatarVideo();
      } else {
        setAvatarStatus("需要 WebRTC（请检查 webrtc_enabled）");
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
    case "vad":
      if (msg.event === "speech_start") {
        liveText.textContent = "检测到说话…";
        // 打断由服务端 turn_cancelled + Gateway 清空媒体缓冲处理；勿 pause WebRTC video
        assistantTurnEl = null;
      } else if (msg.event === "speech_end") {
        liveText.textContent = "语音结束，识别中…";
      } else if (msg.event === "filtered") {
        liveText.textContent = "已忽略背景音";
      }
      break;
    case "user_text":
      syncTurnId(msg);
      assistantTurnEl = null;
      appendMsg("user", msg.text);
      liveText.textContent = msg.text;
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
      break;
    case "assistant_final":
      if (!acceptTurnMsg(msg)) break;
      syncTurnId(msg);
      assistantTurnEl = null;
      break;
    case "turn_cancelled":
      syncTurnId(msg);
      assistantTurnEl = null;
      liveText.textContent = "已打断 AI，请继续说话";
      break;
    case "turn_done":
      syncTurnId(msg);
      finishTurnAndResumeListen();
      break;
    case "reset_ok":
      syncTurnId(msg);
      assistantTurnEl = null;
      if (listeningActive && !listenPaused && authed) resumeListening();
      break;
    case "error":
      appendMsg("system", msg.message);
      if (msg.message && String(msg.message).includes("Avatar")) {
        setAvatarStatus(`Avatar: ${msg.message}`);
      }
      if (listeningActive && !listenPaused && authed) resumeListening();
      break;
  }
}

function finishTurnAndResumeListen() {
  if (listeningActive && !listenPaused && authed) resumeListening();
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
    updateListenButtonState();
    statusText.textContent = "连接已断开";
  };
  ws.onmessage = (e) => {
    handleServerMessage(JSON.parse(e.data));
  };
}

btnToggleListen.addEventListener("click", async () => {
  if (!authed || btnToggleListen.disabled) return;
  resumeAvatarWebRTCPlayback();
  if (!listeningActive) {
    listeningActive = true;
    listenPaused = false;
    btnToggleListen.textContent = "暂停聆听";
    sendJson({ type: "mic_state", enabled: true });
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

btnReset.addEventListener("click", () => {
  chatLog.innerHTML = "";
  assistantTurnEl = null;
  sendJson({ type: "reset" });
});

if (userId) {
  connect();
}
