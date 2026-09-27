import { useCallback, useEffect, useRef, useState } from "react";
import { EMPTY_LIVE_STATE, invalidatesDisplay, metric, pointerRoi, sameFrameContext, validRoi } from "./liveProtocol.js";
import { includesMac, WarningAudio } from "./warningAudio.js";
import { commandReplyEvent, fixedSpeech, isCameraSpeech, RISK_COMMANDS, riskPresentation } from "./riskProtocol.js";
import "./LiveMonitor.css";

const CONNECTION_LABEL = { waiting: "Waiting for phone", connected: "Phone connected", disconnected: "Input disconnected", ended: "Broadcast ended" };
const CAPTURE_LABEL = { waiting: "Waiting for frames", receiving: "Receiving", no_frames: "No new frames", paused: "Capture paused", ended: "Capture ended" };
const MODEL_LABEL = { loading: "Loading model", ready: "Model ready", error: "Model unavailable" };
const ANALYSIS_LABEL = { unanalysed: "Not analyzed", ok: "Analysis complete", empty: "No supported objects detected", error: "Analysis failed" };
const SOURCE_LABEL = { screen_video_test: "Phone video test", diagnostic_video: "Diagnostic video · Mac source" };
const FULL_ROI = [0, 0, 1, 1];
const PERCEPTION_REASON = { input_disconnected: "Video input is disconnected.", model_unavailable: "Vision model is unavailable.", analysis_paused: "Analysis is paused.", observations_stale: "No fresh observations are available.", corridor_unconfigured: "Select a test corridor to assess image overlap.", camera_geometry_only: "Only camera-image geometry is available." };


// Service status messages are emitted in English.

function serviceMessage(message, fallback) {
  if (!message) return fallback;
  return /\p{Script=Han}/u.test(message) ? fallback : message;
}


function paint(canvas, image, boxes = [], corridor = null) {
  if (!canvas) return;
  if (canvas.width !== image.naturalWidth) canvas.width = image.naturalWidth;
  if (canvas.height !== image.naturalHeight) canvas.height = image.naturalHeight;
  const context = canvas.getContext("2d");
  context.clearRect(0, 0, canvas.width, canvas.height);
  context.drawImage(image, 0, 0);
  const size = Math.max(12, Math.round(canvas.width / 65));
  context.font = `600 ${size}px system-ui, sans-serif`;
  context.lineWidth = Math.max(2, canvas.width / 400);
  for (const box of boxes) {
    if (![box.x, box.y, box.w, box.h, box.confidence].every(Number.isFinite)) continue;
    const x = box.x * canvas.width, y = box.y * canvas.height;
    const w = box.w * canvas.width, h = box.h * canvas.height;
    const label = `${box.label} ${Math.round(box.confidence * 100)}%`;
    const labelWidth = Math.min(canvas.width, context.measureText(label).width + 12);
    const labelX = Math.max(0, Math.min(x, canvas.width - labelWidth));
    const labelY = Math.max(0, y - size - 10);
    context.strokeStyle = "#52e4bf";
    context.strokeRect(x, y, w, h);
    context.fillStyle = "#052f2a";
    context.fillRect(labelX, labelY, labelWidth, size + 10);
    context.fillStyle = "#a7ffe9";
    context.fillText(label, labelX + 6, labelY + size + 2);
  }
  if (corridor) {
    context.beginPath();
    corridor.forEach(([x, y], i) => i ? context.lineTo(x*canvas.width, y*canvas.height) : context.moveTo(x*canvas.width, y*canvas.height));
    context.closePath();
    context.strokeStyle = "#f4c76b";
    context.setLineDash([8, 6]);
    context.stroke();
    context.setLineDash([]);
  }
}

function StatusTile({ label, value, tone }) {
  return <div className="live-status-tile"><span>{label}</span><strong className={tone || ""}><i aria-hidden="true" />{value}</strong></div>;
}

export default function LiveMonitor() {
  const [server, setServer] = useState(EMPTY_LIVE_STATE);
  const [socketStatus, setSocketStatus] = useState("connecting");
  const [display, setDisplay] = useState(null);
  const [stale, setStale] = useState(false);
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);
  const [editing, setEditing] = useState(false);
  const [draftRoi, setDraftRoi] = useState(FULL_ROI);
  const [reconnectKey, setReconnectKey] = useState(0);
  const [caseNote, setCaseNote] = useState("");
  const [sourceGroup, setSourceGroup] = useState("");
  const [caseMessage, setCaseMessage] = useState("");
  const [savingCase, setSavingCase] = useState(false);
  const [voiceChoice, setVoiceChoice] = useState("mac");
  const [voiceBusy, setVoiceBusy] = useState(false);
  const [audioStatus, setAudioStatus] = useState({ state: "idle", message: "Voice is off. Enable it to prepare audio.", unlocked: false });
  const [showDistantObjects, setShowDistantObjects] = useState(false);
  const [riskExpired, setRiskExpired] = useState(true);
  const [commandStatus, setCommandStatus] = useState("");
  const riskFreshnessRef = useRef(null);
  const replySequenceRef = useRef(0);
  const showDistantRef = useRef(false);
  const audioRef = useRef(null);
  const voicePendingRef = useRef(null);
  const voiceActionRef = useRef(0);
  const canvasRef = useRef(null);
  const socketRef = useRef(null);
  const serverRef = useRef(EMPTY_LIVE_STATE);
  const imageRef = useRef(null);
  const epochRef = useRef(0);
  const queuedRef = useRef(null);
  const decodingRef = useRef(false);
  const lastDrawnRef = useRef(-1);
  const lastMessageRef = useRef(0);
  const lastFrameRef = useRef(0);
  const staleRef = useRef(false);
  const pendingRef = useRef(null);
  const dragRef = useRef(null);

  // Incrementing the epoch also invalidates images currently awaiting decode/rAF.
  const invalidate = useCallback((clearImage = false, preserveHealth = false) => {
    epochRef.current += 1;
    queuedRef.current = null;
    riskFreshnessRef.current = null;
    setRiskExpired(true);
    if (preserveHealth) audioRef.current?.cancelContext("Camera audio canceled because the video state changed.");
    else audioRef.current?.cancel("Audio canceled because the video state changed.");
    if (clearImage) {
      imageRef.current = null;
      lastDrawnRef.current = -1;
      const canvas = canvasRef.current;
      canvas?.getContext("2d").clearRect(0, 0, canvas.width, canvas.height);
      setDisplay(null);
    } else {
      if (imageRef.current) paint(canvasRef.current, imageRef.current);
      setDisplay((previous) => previous ? { ...previous, boxes: [], risk: null, analysis_status: "unanalysed" } : null);
    }
  }, []);

  useEffect(() => {
    const player = new WarningAudio({ onStatus: setAudioStatus });
    audioRef.current = player;
    return () => {
      player.dispose();
      if (audioRef.current === player) audioRef.current = null;
    };
  }, []);

  useEffect(() => {
    let disposed = false;
    let closeConnection;
    // StrictMode can clean up a trial effect before any network connection exists.
    // The real mount opens one viewer; a failed connection still needs manual retry.
    const connectTimer = setTimeout(() => {
      if (disposed) return;
      const socket = new WebSocket(`${location.protocol === "https:" ? "wss:" : "ws:"}//${location.host}/api/live/viewer`);
      socketRef.current = socket;
      setSocketStatus("connecting");
      setError("");
      setPending(false);
      pendingRef.current = null;
      voicePendingRef.current = null;
      voiceActionRef.current += 1;
      setVoiceBusy(false);
      audioRef.current?.setOutput("off");
      serverRef.current = EMPTY_LIVE_STATE;
      setServer(EMPTY_LIVE_STATE);
      setEditing(false);
      lastFrameRef.current = 0;
      lastMessageRef.current = performance.now();
      staleRef.current = false;
      setStale(false);
      invalidate(true);

      const updateRiskFreshness = (risk, ageMs) => {
        if (!risk || !Number.isFinite(risk.observed_at_s) || !Number.isFinite(risk.expires_at_s)
          || !Number.isFinite(ageMs) || ageMs < 0) return;
        const stamp = `${serverRef.current.session_id}:${risk.observed_at_s}`;
        const deadline = performance.now() + (risk.expires_at_s - risk.observed_at_s) * 1000 - ageMs;
        const previous = riskFreshnessRef.current;
        if (previous && previous.observedAt > risk.observed_at_s) return;
        riskFreshnessRef.current = { stamp, observedAt: risk.observed_at_s,
          deadline: previous?.stamp === stamp ? Math.min(previous.deadline, deadline) : deadline };
        setRiskExpired(riskFreshnessRef.current.deadline <= performance.now());
        if (risk.lifecycle === "image_conflict_resolved" || risk.lifecycle === "occluded_unresolved" || risk.lifecycle === "unknown") {
          audioRef.current?.cancelEvidence("Earlier camera evidence is no longer current.");
        }
      };

      const pumpFrames = async () => {
        if (decodingRef.current) return;
        decodingRef.current = true;
        try {
          while (!disposed && queuedRef.current) {
            const frame = queuedRef.current;
            queuedRef.current = null;
            const epoch = epochRef.current;
            const image = new Image();
            image.src = `data:image/jpeg;base64,${frame.image_b64}`;
            try {
              await image.decode();
            } catch {
              if (!disposed && epoch === epochRef.current) setError("Could not decode this frame. Waiting for the next frame.");
              continue;
            }
            if (disposed || epoch !== epochRef.current || staleRef.current || pendingRef.current
              || !sameFrameContext(frame, serverRef.current) || frame.frame_id <= lastDrawnRef.current) continue;
            imageRef.current = image;
            lastDrawnRef.current = frame.frame_id;
            const allBoxes = frame.analysis_status === "ok" && serverRef.current.analysis_enabled ? frame.boxes || [] : [];
            // Filter only this decoded frame, using one list for both canvas and results.
            // Older receivers without attention metadata remain visible during upgrades.
            const showDistant = showDistantRef.current;
            const boxes = showDistant ? allBoxes : allBoxes.filter((box) => box.attention?.near !== false);
            paint(canvasRef.current, image, boxes, serverRef.current.corridor);
            const risk = frame.risk || null;
            updateRiskFreshness(risk, Number.isFinite(frame.server_frame_age_ms)
              ? frame.server_frame_age_ms + performance.now() - frame.receivedAt : NaN);
            if (risk?.event && !voicePendingRef.current && includesMac(serverRef.current.voice?.output)
              && serverRef.current.perception?.status === "limited" && Number.isFinite(frame.server_frame_age_ms)) {
              audioRef.current?.enqueue(risk.event, { ageMs: frame.server_frame_age_ms, receivedAt: frame.receivedAt });
            }
            setDisplay({ frame_id: frame.frame_id, revision: frame.revision, session_id: frame.session_id,
              width: image.naturalWidth, height: image.naturalHeight,
              analysis_status: frame.analysis_status, boxes, risk,
              show_distant_objects: showDistant, hidden_distant_count: allBoxes.length - boxes.length });
            // The acknowledgement refers to the frame actually decoded and painted.
            requestAnimationFrame(() => {
              if (!disposed && epoch === epochRef.current && lastDrawnRef.current === frame.frame_id
                && !staleRef.current && !pendingRef.current && sameFrameContext(frame, serverRef.current)
                && socket.readyState === WebSocket.OPEN) {
                socket.send(JSON.stringify({ type: "display_ack", session_id: frame.session_id,
                  frame_id: frame.frame_id, revision: frame.revision }));
              }
            });
          }
        } finally {
          decodingRef.current = false;
        }
      };

      socket.onopen = () => { if (!disposed) setSocketStatus("connected"); };
      socket.onmessage = ({ data }) => {
        if (disposed) return;
        lastMessageRef.current = performance.now();
        let message;
        try { message = JSON.parse(data); } catch { setError("Received an invalid message from the service."); return; }
        if (message.type === "state") {
          const previous = serverRef.current;
          const contextChanged = previous.session_id !== message.session_id
            || String(previous.dimensions) !== String(message.dimensions);
          if (invalidatesDisplay(previous, message)) {
            invalidate(contextChanged || previous.revision !== message.revision, !contextChanged);
          }
          if (JSON.stringify(previous.corridor) !== JSON.stringify(message.corridor)) {
            audioRef.current?.cancel("Audio canceled because the test corridor changed.");
          }
          if (contextChanged) {
            setEditing(false);
            setDraftRoi(FULL_ROI);
            pendingRef.current = null;
            setPending(false);
            lastFrameRef.current = 0;
          }
          serverRef.current = message;
          setServer(message);
          updateRiskFreshness(message.risk, message.perception?.frame_age_ms);
          if (message.perception?.status === "unavailable") {
            audioRef.current?.cancelEvidence("Visual guidance is unavailable.");
          }
          const output = message.voice?.output || "off";
          if (voicePendingRef.current?.output === output) {
            voicePendingRef.current = null;
            setVoiceBusy(false);
          }
          if (output !== "off") setVoiceChoice(output);
          audioRef.current?.setOutput(voicePendingRef.current ? "off" : output);
          if (pendingRef.current && message.revision > pendingRef.current.revision) {
            pendingRef.current = null;
            setPending(false);
          }
          if (message.connection !== "connected" || message.capture !== "receiving") {
            if (!staleRef.current) invalidate(false, true);
            staleRef.current = true;
            setStale(true);
          }
        } else if (message.type === "frame") {
          if (!sameFrameContext(message, serverRef.current) || pendingRef.current
            || !Number.isInteger(message.frame_id) || message.frame_id <= lastDrawnRef.current) return;
          lastFrameRef.current = performance.now();
          staleRef.current = false;
          setStale(false);
          queuedRef.current = { ...message, receivedAt: performance.now() };
          void pumpFrames();
        } else if (message.type === "voice_stop") {
          invalidate();
        } else if (message.type === "voice_event") {
          const cameraEvent = isCameraSpeech(message.event?.speech_code);
          if (!voicePendingRef.current && includesMac(serverRef.current.voice?.output)
            && (!cameraEvent || (!staleRef.current && serverRef.current.analysis_enabled && serverRef.current.perception?.status === "limited"))) {
            audioRef.current?.enqueue(message.event, { ageMs: Math.max(0, message.server_event_age_ms || 0), receivedAt: performance.now() });
          }
        } else if (message.type === "command_reply") {
          const event = commandReplyEvent(message, `reply-${++replySequenceRef.current}`);
          if (!event && message.command === "repeat" && !message.speech) setCommandStatus("Repeat request processed.");
          if (event) {
            setCommandStatus(fixedSpeech(event));
            if (!voicePendingRef.current && includesMac(serverRef.current.voice?.output)) {
              audioRef.current?.enqueue(event, { receivedAt: performance.now() });
            }
          }
        } else if (message.type === "case_saved") {
          setSavingCase(false);
          setCaseMessage(`Saved ${message.frames} frames: ${message.case_id}. Ready for manual annotation.`);
        } else if (message.type === "error") {
          setSavingCase(false);
          setError(serviceMessage(message.message, "The service could not complete this action."));
          pendingRef.current = null;
          setPending(false);
        }
      };
      socket.onerror = () => { if (!disposed) setError("Could not connect to SkyCompanion. Check that the service is running and only one live monitor is open."); };
      socket.onclose = (event) => {
        if (disposed) return;
        invalidate();
        voiceActionRef.current += 1;
        voicePendingRef.current = null;
        setVoiceBusy(false);
        audioRef.current?.setOutput("off");
        setSocketStatus("disconnected");
        setSavingCase(false);
        staleRef.current = true;
        setStale(true);
        pendingRef.current = null;
        setPending(false);
        if (event.code === 1008) setError("This connection was rejected. Close other live monitors, then reconnect.");
      };

      const watchdog = setInterval(() => {
        const now = performance.now();
        if (riskFreshnessRef.current && now >= riskFreshnessRef.current.deadline) {
          setRiskExpired(true);
          audioRef.current?.cancelEvidence("Camera evidence has expired.");
          riskFreshnessRef.current = null;
        }
        const lostFrames = lastFrameRef.current > 0 && now - lastFrameRef.current > 2000;
        const lostServer = now - lastMessageRef.current > 3500;
        if ((lostFrames || lostServer) && !staleRef.current) {
          staleRef.current = true;
          setStale(true);
          invalidate(false, !lostServer);
        }
        if (pendingRef.current && now - pendingRef.current.sentAt > 5000) {
          pendingRef.current = null;
          setPending(false);
          setError("The service has not confirmed this action. Check the connection, then try again.");
        }
        if (voicePendingRef.current && !voicePendingRef.current.timedOut && now - voicePendingRef.current.sentAt > 5000) {
          voicePendingRef.current.timedOut = true;
          setVoiceBusy(false);
          setAudioStatus((previous) => ({ ...previous, state: "error", message: "The service has not confirmed the voice output. Mac audio remains stopped; retry the selection." }));
        }
      }, 250);
      closeConnection = () => {
        clearInterval(watchdog);
        voiceActionRef.current += 1;
        invalidate(true);
        socket.onclose = null;
        socket.close();
        if (socketRef.current === socket) socketRef.current = null;
      };
    }, 0);
    return () => {
      disposed = true;
      clearTimeout(connectTimer);
      closeConnection?.();
    };
  }, [reconnectKey, invalidate]);

  function configure(roi, analysisEnabled) {
    const socket = socketRef.current;
    const current = serverRef.current;
    if (socket?.readyState !== WebSocket.OPEN || !current.session_id || pendingRef.current) return false;
    if (JSON.stringify(current.roi) === JSON.stringify(roi) && current.analysis_enabled === analysisEnabled) return true;
    invalidate(true);
    setError("");
    pendingRef.current = { revision: current.revision, sentAt: performance.now() };
    setPending(true);
    socket.send(JSON.stringify({ type: "configure", session_id: current.session_id, roi, analysis_enabled: analysisEnabled }));
    return true;
  }

  function beginCrop() {
    if (configure(null, false)) {
      setDraftRoi(FULL_ROI);
      setEditing(true);
    }
  }

  function saveCase(reason) {
    if (!display || socketRef.current?.readyState !== WebSocket.OPEN || savingCase) return;
    socketRef.current.send(JSON.stringify({ type: "save_case", session_id: display.session_id,
      revision: display.revision, frame_id: display.frame_id, reason, note: caseNote, source_group: sourceGroup }));
    setSavingCase(true);
    setCaseMessage("Saving this frame and its context. Keep the video playing for about 4 seconds.");
  }

  function control(message) {
    if (socketRef.current?.readyState !== WebSocket.OPEN) return false;
    if (message.type === "corridor") audioRef.current?.cancel("Audio canceled because the test corridor changed.");
    socketRef.current.send(JSON.stringify({ session_id: server.session_id, revision: server.revision, ...message }));
    return true;
  }

  function riskCommand(command) {
    if (!Object.hasOwn(RISK_COMMANDS, command)) return;
    if (control({ type: "risk_command", command })) setCommandStatus("Request sent.");
  }

  async function selectVoiceOutput(output) {
    const action = ++voiceActionRef.current;
    setVoiceBusy(true);
    let awaitingConfirmation = false;
    try {
      audioRef.current?.setOutput("off"); // Stop immediately; await the server before resuming.
      if (includesMac(output) && !await audioRef.current?.unlock()) return;
      if (action !== voiceActionRef.current) return;
      voicePendingRef.current = { output, sentAt: performance.now() };
      awaitingConfirmation = control({ type: "voice_output", output });
      if (!awaitingConfirmation) {
        voicePendingRef.current = null;
        setAudioStatus((previous) => ({ ...previous, state: "error", message: "Voice output was not changed: reconnect to the receiver first." }));
      }
    } catch (error) {
      if (action === voiceActionRef.current) {
        voicePendingRef.current = null;
        setAudioStatus((previous) => ({ ...previous, state: "error", message: `Voice setup failed: ${error?.message || "Unexpected audio error."} Try Enable voice again.` }));
      }
    } finally {
      if (action === voiceActionRef.current && !awaitingConfirmation) setVoiceBusy(false);
    }
  }

  async function prepareMacAudio(test = false) {
    const action = ++voiceActionRef.current;
    setVoiceBusy(true);
    try {
      const output = serverRef.current.voice?.output || "off";
      const ready = !includesMac(output) || await audioRef.current?.unlock();
      if (action !== voiceActionRef.current || !ready) return;
      audioRef.current?.setOutput(serverRef.current.voice?.output || "off");
      if (test && !control({ type: "voice_test" })) {
        setAudioStatus((previous) => ({ ...previous, state: "error", message: "Voice test could not be sent. Reconnect to the receiver." }));
      }
    } catch (error) {
      if (action === voiceActionRef.current) {
        setAudioStatus((previous) => ({ ...previous, state: "error", message: `Voice setup failed: ${error?.message || "Unexpected audio error."} Try Test voice again.` }));
      }
    } finally {
      if (action === voiceActionRef.current) setVoiceBusy(false);
    }
  }

  function pointerPosition(event) {
    const rect = event.currentTarget.getBoundingClientRect();
    return [Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width)),
      Math.max(0, Math.min(1, (event.clientY - rect.top) / rect.height))];
  }

  const connected = socketStatus === "connected" && server.connection === "connected";
  const receiving = connected && server.capture === "receiving" && !stale;
  const editable = receiving && !pending && Boolean(display);
  const canStart = editable && server.model?.state === "ready" && validRoi(server.roi) && !editing && !server.analysis_enabled;
  const captureLabel = stale && server.capture === "receiving" ? "No new frames" : CAPTURE_LABEL[server.capture] || "Waiting for frames";
  const metrics = server.metrics || {};
  const currentRisk = (display?.risk?.observed_at_s ?? -Infinity) > (server.risk?.observed_at_s ?? -Infinity) ? display.risk : server.risk || display?.risk;
  const riskView = riskPresentation(receiving ? currentRisk : null, server.perception, {
    perceptionAvailable: receiving && server.analysis_enabled && !pending,
    available: receiving && server.analysis_enabled && !pending && !riskExpired && server.perception?.status !== "unavailable",
  });
  const voice = { output: "off", phone_connected: false, ...server.voice };
  const voiceActive = voice.output !== "off";
  const currentAnalysis = receiving && !pending ? display?.analysis_status || "unanalysed" : "unanalysed";
  const noNearbyCandidates = (currentAnalysis === "ok" || currentAnalysis === "empty")
    && display?.boxes.length === 0 && !display.show_distant_objects;
  const analysisLabel = noNearbyCandidates ? "No nearby candidates in this frame" : ANALYSIS_LABEL[currentAnalysis];
  const modeLabel = editing ? "Select video area" : server.analysis_enabled ? "Analyzing selected area" : validRoi(server.roi) ? "Area saved · Ready to analyze" : "Full-screen preview";

  return (
    <div className="live-layout" lang="en">
      <header className="live-header">
        <div><a className="live-brand" href="/">SkyCompanion<span>Vision workspace</span></a><h1>Live vision</h1>
          <p>Start an SkyCompanion screen broadcast on your iPhone, switch to a video player, and view the live detections here.</p></div>
        <a href="/" className="live-link">Analyze a video file ↗</a>
      </header>

      <div className="live-status-grid" aria-label="System status" aria-live="polite">
        <StatusTile label="Receiver" value={socketStatus === "connected" ? "Connected" : socketStatus === "connecting" ? "Connecting" : "Disconnected"} tone={socketStatus === "connected" ? "good" : "warn"} />
        <StatusTile label={server.source === "diagnostic_video" ? "Diagnostic input" : "Phone input"} value={server.source === "diagnostic_video" && server.connection === "connected" ? "Mac source connected" : CONNECTION_LABEL[server.connection] || "Waiting for phone"} tone={connected ? "good" : "warn"} />
        <StatusTile label="Screen capture" value={captureLabel} tone={receiving ? "good" : "warn"} />
        <StatusTile label="Local inference" value={MODEL_LABEL[server.model?.state] || "Waiting for model"} tone={server.model?.state === "ready" ? "good" : server.model?.state === "error" ? "bad" : "warn"} />
      </div>

      {socketStatus === "disconnected" ? <div className="live-notice" role="status"><span>The monitor disconnected. Previous detections have been cleared.</span><button className="live-button" onClick={() => setReconnectKey((value) => value + 1)}>Reconnect</button></div> : null}
      {error ? <div className="live-error" role="alert"><span>{error}</span><button aria-label="Dismiss error" onClick={() => setError("")}>×</button></div> : null}
      {server.model?.error ? <div className="live-error" role="alert">Model error: {serviceMessage(server.model.error, "The local model could not run. Check the receiver log.")}</div> : null}

      <main className="live-workspace">
        <section className="live-panel live-video-panel" aria-labelledby="live-video-title">
          <div className="live-panel-heading"><div><h2 id="live-video-title">{modeLabel}</h2><p>{SOURCE_LABEL[server.source] || "Waiting for a screen broadcast"}</p></div><span className={`live-pill ${receiving ? "active" : ""}`}>{receiving ? "LIVE" : "STANDBY"}</span></div>
          <div className={`live-stage ${editing && editable ? "cropping" : ""}`}>
            <div className="live-canvas-wrap" style={display ? { aspectRatio: `${display.width} / ${display.height}`, width: `min(100%, calc(65vh * ${display.width / display.height}))` } : { aspectRatio: "16 / 9" }}
              onPointerDown={(event) => {
                if (!editing || !editable) return;
                event.preventDefault();
                event.currentTarget.setPointerCapture(event.pointerId);
                dragRef.current = pointerPosition(event);
                setDraftRoi([...dragRef.current, 0, 0]);
              }}
              onPointerMove={(event) => { if (dragRef.current) setDraftRoi(pointerRoi(dragRef.current, pointerPosition(event))); }}
              onPointerUp={(event) => {
                if (!dragRef.current) return;
                setDraftRoi(pointerRoi(dragRef.current, pointerPosition(event)));
                dragRef.current = null;
                if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
              }}
              onPointerCancel={() => { dragRef.current = null; }}>
              <canvas ref={canvasRef} width="960" height="540" aria-label="Live phone view with detections for this frame" style={{ display: display ? "block" : "none" }} />
              {!display ? <div className="live-placeholder"><span aria-hidden="true">▣</span><strong>{pending ? "Updating preview…" : "Waiting for phone video"}</strong><p>{pending ? "New frames will appear once the settings take effect." : "In SkyCompanionCapture, check the connection and start a screen broadcast, then open your video player."}</p></div> : null}
              {editing && display ? <div className="live-crop-box" style={{ left: `${draftRoi[0] * 100}%`, top: `${draftRoi[1] * 100}%`, width: `${draftRoi[2] * 100}%`, height: `${draftRoi[3] * 100}%` }}><span>Video area</span></div> : null}
              {display && !receiving ? <div className="live-stale-mask"><span>{captureLabel} · Detections cleared</span></div> : null}
            </div>
          </div>
          <div className="live-frame-caption"><span>{display ? `${display.width} × ${display.height} · Frame ${display.frame_id}` : "Only the screen you choose to share is shown"}</span><span>{analysisLabel}</span></div>

          <div className="live-controls">
            {editing ? <>
              <p className="live-help">Drag to select the video area, or enter percentages below. Save the area, then start analysis.</p>
              <div className="live-roi-fields">{["Left", "Top", "Width", "Height"].map((label, index) => <label key={label}>{label} %<input type="number" inputMode="decimal" min="0" max="100" step="0.1" value={Number((draftRoi[index] * 100).toFixed(1))} disabled={!editable}
                onChange={(event) => setDraftRoi((previous) => previous.map((value, i) => i === index ? Number(event.target.value) / 100 : value))} /></label>)}</div>
              {!validRoi(draftRoi) ? <p className="live-field-error">The area must fit within the frame and be at least 2% wide and high.</p> : null}
              <div className="live-actions"><button className="live-button primary" disabled={!editable || !validRoi(draftRoi)} onClick={() => { if (configure(draftRoi, false)) setEditing(false); }}>Save video area</button>
                <button className="live-button" disabled={!editable} onClick={() => setDraftRoi(FULL_ROI)}>Use full frame</button></div>
            </> : <><div className="live-actions"><button className="live-button primary" disabled={!canStart} onClick={() => configure(server.roi, true)}>Start analysis</button>
              <button className="live-button" disabled={!connected || pending || !server.analysis_enabled} onClick={() => configure(server.roi, false)}>Pause analysis</button>
              <button className="live-button" disabled={!editable} onClick={beginCrop}>{validRoi(server.roi) ? "Reselect video area" : "Select video area"}</button></div>
              <p className="live-help">{pending ? "Waiting for the service to confirm settings." : !validRoi(server.roi) ? "Once the phone video appears, select and save the video area." : "Selecting a new area pauses analysis. Confirm the area again after rotating or reconnecting the phone."}</p></>}
            {server.message ? <p className="live-help" role="status">{serviceMessage(server.message, "Waiting for the next service update.")}</p> : null}
          </div>
        </section>

        <aside className="live-sidebar">
          <section className="live-panel live-risk-panel" aria-labelledby="live-risk-title">
            <div className="live-panel-heading"><h2 id="live-risk-title">Risk evidence</h2><span className="live-small-pill">Camera view</span></div>
            <div className="live-evidence-fields">
              <p className={`live-risk-level ${riskView.level === "R3" ? "bad" : ""}`}>{riskView.levelText}</p>
              <p className="live-sr-only" role="status" aria-live="polite" aria-atomic="true">{riskView.levelText}. Perception {riskView.health.toLowerCase()}. {riskView.lifecycleText}.</p>
              <dl className="live-risk-facts">
                <div><dt>Perception health</dt><dd>{riskView.health}</dd></div>
                <div><dt>Observation</dt><dd>{riskView.lifecycleText}</dd></div>
                <div><dt>Presence confidence</dt><dd>{riskView.confidence.presence}</dd></div>
                <div><dt>Path confidence</dt><dd>{riskView.confidence.path}</dd></div>
                <div><dt>Category confidence</dt><dd>{riskView.confidence.category}</dd></div>
                <div><dt>Distance confidence</dt><dd>{riskView.confidence.distance}</dd></div>
              </dl>
              <p>{receiving ? PERCEPTION_REASON[server.perception?.reason] || "Waiting for perception status." : "Live observations are unavailable."}</p>
              <p>{riskView.direction}. Wearer direction: unknown. Distance: unmeasured.</p>
              {riskView.reasons.length ? <ul className="live-risk-reasons">{riskView.reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul> : null}
              <p>R0 means no image conflict is confirmed. It does not establish a safe or clear path.</p>
              <p>Automatic alerts focus on changes. Same-level updates are spaced out; urgent escalation is not delayed.</p>
              <div className="live-actions" aria-label="Risk controls">
                {Object.entries(RISK_COMMANDS).filter(([command]) => command !== (server.risk_preferences?.quiet ? "quiet" : "normal")).map(([command, label]) =>
                  <button key={command} className="live-button" disabled={socketStatus !== "connected"} onClick={() => riskCommand(command)}>{label}</button>)}
              </div>
              <p>Alert mode: {server.risk_preferences?.quiet ? "Quiet · higher-priority alerts remain active" : "Normal"}</p>
              <p role="status" aria-live="polite" aria-atomic="true">{commandStatus}</p>
            </div>
          </section>
          <section className="live-panel"><div className="live-panel-heading"><h2>Vision and alerts</h2></div>
            <div className="live-evidence-fields">
              <div className="live-model-summary"><strong>SkyCompanion Vision</strong><span className="live-small-pill">Experimental</span></div>
              <p>Obstacle detection is experimental. Additional classes are still being evaluated.</p>
              <button className="live-button" disabled={!receiving || !server.analysis_enabled} onClick={() => control({ type: "corridor", points: server.corridor ? null : [[.4,.45],[.6,.45],[.85,1],[.15,1]] })}>{server.corridor ? "Clear test corridor" : "Use center as test corridor"}</button>
              <p>The yellow outline marks the image area you selected. It does not establish a sidewalk or a clear path.</p>
              <label>Playback on<select aria-label="Playback on" value={voiceActive ? voice.output : voiceChoice}
                disabled={socketStatus !== "connected" || voiceBusy} onChange={(event) => {
                  setVoiceChoice(event.target.value);
                  if (voiceActive) void selectVoiceOutput(event.target.value);
                  else audioRef.current?.cancel("Audio canceled because the output selection changed.");
                }}><option value="mac">Mac</option><option value="phone">iPhone</option><option value="both">Both</option></select></label>
              <div className="live-actions"><button className="live-button" disabled={socketStatus !== "connected" || voiceBusy}
                onClick={() => void selectVoiceOutput(voiceActive ? "off" : voiceChoice)}>{voiceActive ? "Disable voice" : "Enable voice"}</button>
                <button className="live-button" disabled={socketStatus !== "connected" || !voiceActive || voiceBusy}
                  onClick={() => void prepareMacAudio(true)}>Test voice</button></div>
              {voiceActive && includesMac(voice.output) && !audioStatus.unlocked ? <button className="live-button" disabled={voiceBusy}
                onClick={() => void prepareMacAudio()}>Enable Mac audio</button> : null}
              <p>Voice: {voiceActive ? voice.output === "both" ? "Mac and iPhone" : voice.output === "phone" ? "iPhone" : "Mac" : "off"}{voiceBusy ? " · Updating…" : ""}</p>
              <p className={`live-audio-status ${audioStatus.state === "error" ? "bad" : audioStatus.state === "fallback" ? "warn" : ""}`}
                role={audioStatus.state === "error" ? "alert" : undefined}>{audioStatus.message}</p>
              <p className={voice.last_phone_ack?.stage === "failed" ? "live-audio-status bad" : ""}
                role={voice.last_phone_ack?.stage === "failed" ? "alert" : "status"}>{voice.phone_connected ? "iPhone voice receiver connected." : "iPhone voice receiver is not connected."}
                {voice.last_phone_ack?.stage === "failed" ? " iPhone playback failed. Check SkyCompanionCapture and its audio output." : voice.last_phone_ack?.stage ? ` Last iPhone acknowledgment: ${voice.last_phone_ack.stage}.` : ""}</p>
              <p>{voice.phone_capability === "active_speech_session" ? "iPhone reports an active voice assistance session. English commands and alerts can continue across apps while its microphone session remains active." : "For cross-app iPhone audio, start Continuous voice assistance in SkyCompanionCapture before switching apps. Without it, keep SkyCompanionCapture in the foreground."}</p>
              <p>iPhone voice and speed are selected in SkyCompanionCapture. Mac risk alerts use browser voice with fixed camera-relative wording. Describe ahead summarizes visible objects; automatic alerts require stable corridor evidence. Playback callbacks do not measure when sound reaches your ears.</p>
            </div>
          </section>
          <section className="live-panel" aria-labelledby="live-evidence-title"><div className="live-panel-heading"><h2 id="live-evidence-title">Save an issue</h2></div>
            <div className="live-evidence-fields">
              <label>Video / location<input value={sourceGroup} maxLength={120} placeholder="Use one name for the same video" onChange={(e) => setSourceGroup(e.target.value)} /></label>
              <label>Issue description<input value={caseNote} maxLength={500} placeholder="Example: missed barrel / fence labeled as train" onChange={(e) => setCaseNote(e.target.value)} /></label>
              <div className="live-actions"><button className="live-button" disabled={!receiving || !display || savingCase} onClick={() => saveCase("missed_obstacle")}>Save missed object</button>
                <button className="live-button" disabled={!receiving || !display || savingCase} onClick={() => saveCase("wrong_label")}>Save wrong label</button></div>
              <p role="status">{caseMessage || "Saves this frame and up to 4 seconds on either side to this computer. Predictions and manual annotations are stored separately."}</p>
            </div>
          </section>
          <section className="live-panel" aria-labelledby="live-results-title"><div className="live-panel-heading"><h2 id="live-results-title">Current detections</h2><span className="live-small-pill">SkyCompanion Vision</span></div>
            <div className="live-attention-controls">
              <strong>Nearby objects first</strong>
              <label><input type="checkbox" checked={showDistantObjects} onChange={(event) => {
                showDistantRef.current = event.target.checked;
                setShowDistantObjects(event.target.checked);
              }} />Show distant objects</label>
              <p>Priority uses image position and size, not measured distance.</p>
            </div>
            <div className={`live-result-state ${currentAnalysis === "error" ? "bad" : ""}`}>{analysisLabel}</div>
            {currentAnalysis === "ok" && display?.boxes.length ? <ul className="live-detections">{display.boxes.map((box, index) => <li key={`${box.class_id}-${index}`}><span>{box.label}</span><strong>{Math.round(box.confidence * 100)}%</strong></li>)}</ul> : <p className="live-sidebar-copy">{noNearbyCandidates ? "The nearby filter has no candidates for this frame. This does not mean the path is clear." : currentAnalysis === "empty" || currentAnalysis === "ok" ? "Analysis finished for this frame with no supported objects displayed." : currentAnalysis === "error" ? "Analysis failed. Check the model status and error message." : "Start analysis to see object labels and confidence scores for the current frame."}</p>}
            {currentAnalysis === "ok" && display?.hidden_distant_count > 0 ? <p className="live-sidebar-copy">{display.hidden_distant_count} distant {display.hidden_distant_count === 1 ? "detection hidden" : "detections hidden"}.</p> : null}
            <p className="live-limitation">No detections does not mean the path is clear. This test evaluates screen capture and object detection.</p>
          </section>

          <section className="live-panel" aria-labelledby="live-metrics-title"><div className="live-panel-heading"><h2 id="live-metrics-title">Transfer and processing</h2><span className="live-small-pill">{server.model?.device === "mps" ? "Apple GPU" : "Local CPU"}</span></div>
            <dl className="live-metrics">{[
              ["Received frame rate", metric(metrics.received_fps, 1, " fps")],
              ["Inference frame rate", metric(metrics.processed_fps, 1, " fps")],
              ["Stale frames dropped", metric(metrics.dropped_frames, 0)],
              ["Queue time", metric(metrics.queue_ms, 0, " ms")],
              ["Inference per frame", metric(metrics.inference_ms, 0, " ms")],
              ["Display round trip P50", metric(metrics.roundtrip_p50_ms, 0, " ms")],
              ["Display round trip P95", metric(metrics.roundtrip_p95_ms, 0, " ms")],
            ].map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>
            <p className="live-sidebar-copy">{server.source === "diagnostic_video" ? "Measured by the Mac diagnostic sender: sending, processing, browser rendering, and acknowledgment. This is not phone or drone latency." : "Measured by the phone: capture, processing, browser rendering, and acknowledgment. This is not full drone latency."}</p>
          </section>
        </aside>
      </main>
      <footer className="live-footer"><span>Phone broadcast → Frame sampling → Local vision on Mac → Live detections</span><span>Keep your phone and Mac on the same Wi-Fi during the test</span></footer>
    </div>
  );
}
