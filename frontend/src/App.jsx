import { useCallback, useEffect, useRef, useState } from "react";
import "./App.css";

const API = "/api";

const STATUS_PROGRESS = {
  uploading: { value: 8, label: "Uploading video" },
  queued: { value: 16, label: "Waiting for backend" },
  extracting: { value: 28, label: "Extracting video frames" },
  summarizing: { value: 78, label: "Generating Gemini safety advice" },
  rendering: { value: 90, label: "Rendering marked video" },
  completed: { value: 100, label: "Completed" },
  failed: { value: 100, label: "Failed" },
};

async function fetchJson(url, options) {
  const res = await fetch(url, options);
  const text = await res.text();
  let data = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = { detail: text || res.statusText };
  }
  if (!res.ok) {
    const msg = data?.detail ?? data?.message ?? res.statusText;
    throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
  }
  return data;
}

export default function App() {
  const [file, setFile] = useState(null);
  const [devicePanelOpen, setDevicePanelOpen] = useState(false);
  const [selectedDevice, setSelectedDevice] = useState("");
  const [deviceConnected, setDeviceConnected] = useState(false);
  const [jobId, setJobId] = useState(null);
  const [status, setStatus] = useState(null);
  const [summary, setSummary] = useState(null);
  const [geminiSummary, setGeminiSummary] = useState(null);
  const [obstacleProgress, setObstacleProgress] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const pollRef = useRef(null);

  const reset = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
    setFile(null);
    setJobId(null);
    setStatus(null);
    setSummary(null);
    setGeminiSummary(null);
    setObstacleProgress(null);
    setError(null);
    setBusy(false);
  }, []);

  const pollJob = useCallback((id) => {
    if (pollRef.current) clearInterval(pollRef.current);
    pollRef.current = setInterval(async () => {
      try {
        const j = await fetchJson(`${API}/jobs/${id}`);
        setStatus(j.status);
        if (j.summary) setSummary(j.summary);
        if (j.gemini_summary) setGeminiSummary(j.gemini_summary);
        if (j.obstacle_progress) setObstacleProgress(j.obstacle_progress);
        if (j.status === "completed" || j.status === "failed") {
          clearInterval(pollRef.current);
          pollRef.current = null;
          setBusy(false);
          if (j.status === "failed" && j.error) setError(j.error);
        }
      } catch (e) {
        setError(e.message);
        clearInterval(pollRef.current);
        pollRef.current = null;
        setBusy(false);
      }
    }, 1200);
  }, []);

  useEffect(() => () => pollRef.current && clearInterval(pollRef.current), []);

  const onSubmit = async (e) => {
    e.preventDefault();
    if (!file) return;
    reset();
    setBusy(true);
    setError(null);
    setStatus("uploading");
    try {
      const fd = new FormData();
      fd.append("file", file);
      const created = await fetchJson(`${API}/jobs`, { method: "POST", body: fd });
      setJobId(created.job_id);
      setStatus("queued");
      pollJob(created.job_id);
    } catch (e) {
      setError(e.message);
      setBusy(false);
      setStatus(null);
    }
  };

  const onAutoConnect = () => {
    setDevicePanelOpen(true);
    setSelectedDevice("DJI Neo 2");
    setDeviceConnected(true);
  };

  const downloadUrl =
    jobId && status === "completed" ? `${API}/jobs/${jobId}/download` : null;
  const obstacleTotal = Number(obstacleProgress?.total_frames ?? 0);
  const obstacleProcessed = Number(obstacleProgress?.processed_frames ?? 0);
  const obstaclePercent =
    obstacleTotal > 0 ? Math.round((obstacleProcessed / obstacleTotal) * 100) : 0;
  const progress =
    status === "analyzing_obstacles"
      ? {
          value: obstaclePercent,
          label:
            obstacleTotal > 0
              ? `Analyzing obstacles: ${obstacleProcessed}/${obstacleTotal} frames`
              : "Preparing obstacle analysis",
        }
      : status
        ? STATUS_PROGRESS[status] ?? { value: 35, label: status }
        : null;

  return (
    <div className="layout">
      <header className="header">
        <div className="brand">
          <span className="logo">SkyCompanion</span>
          <span className="tagline">Video object marker</span>
        </div>
        <p className="lede">
          Upload a clip. SkyCompanion uses Roboflow visual workflows and Gemini safety reasoning to
          mark ski hazards and return a guided video.
        </p>
      </header>

      <main className="card">
        <form className="form" onSubmit={onSubmit}>
          <label className="file-label">
            <input
              type="file"
              accept="video/mp4,video/quicktime,video/x-msvideo,video/x-matroska,video/webm"
              onChange={(e) => {
                reset();
                setFile(e.target.files?.[0] ?? null);
              }}
              disabled={busy}
            />
            <span className="file-prompt">
              {file ? file.name : "Choose a video file…"}
            </span>
          </label>

          <section className="device-card" aria-label="Device connection">
            <div>
              <p className="device-kicker">Live source</p>
              <h2 className="device-title">Connect a camera device</h2>
              <p className="device-copy">
                Auto connect to a nearby capture device for future live video input.
              </p>
            </div>
            <button
              type="button"
              className="btn ghost device-trigger"
              onClick={onAutoConnect}
              disabled={busy}
            >
              Auto connect to device
            </button>
            {devicePanelOpen && (
              <div className="device-select-row">
                <label htmlFor="device-select">Select device</label>
                <select
                  id="device-select"
                  value={selectedDevice}
                  onChange={(e) => {
                    setSelectedDevice(e.target.value);
                    setDeviceConnected(Boolean(e.target.value));
                  }}
                  disabled={busy}
                >
                  <option value="">Choose a device…</option>
                  <option value="DJI Neo 2">DJI Neo 2</option>
                </select>
                {deviceConnected && (
                  <span className="device-pill">Connected: {selectedDevice}</span>
                )}
              </div>
            )}
          </section>

          <div className="actions">
            <button type="submit" className="btn primary" disabled={!file || busy}>
              {busy ? "Processing…" : "Run AI marking"}
            </button>
            {(file || jobId) && !busy && (
              <button type="button" className="btn ghost" onClick={reset}>
                Clear
              </button>
            )}
          </div>
        </form>

        {error && (
          <div className="banner error" role="alert">
            {error}
          </div>
        )}

        {status && (
          <div className="status-block">
            <h2 className="status-title">Job status</h2>
            {progress && (
              <div
                className={`progress-card ${status === "failed" ? "failed" : ""}`}
                aria-label={`Progress: ${progress.label}`}
              >
                <div className="progress-meta">
                  <span>{progress.label}</span>
                  <strong>{progress.value}%</strong>
                </div>
                <div
                  className="progress-track"
                  role="progressbar"
                  aria-valuemin="0"
                  aria-valuemax="100"
                  aria-valuenow={progress.value}
                >
                  <span
                    className="progress-fill"
                    style={{ width: `${progress.value}%` }}
                  />
                </div>
              </div>
            )}
            <p className="status-line">
              <span className="mono">{jobId ?? "—"}</span>
            </p>
            <p className="status-line">
              State: <strong>{status}</strong>
            </p>
            {summary && (
              <div className="summary">
                <p>
                  Tracks: <strong>{summary.track_count}</strong>
                </p>
                {summary.labels?.length > 0 && (
                  <p className="labels">
                    Labels:{" "}
                    {summary.labels.map((l) => (
                      <span key={l} className="chip">
                        {l}
                      </span>
                    ))}
                  </p>
                )}
              </div>
            )}
            {geminiSummary && (
              <div className="safety-card">
                <h3>Gemini safety copilot</h3>
                <p>
                  Level: <strong>{geminiSummary.hazard_level}</strong>
                </p>
                <p>{geminiSummary.primary_hazard}</p>
                <p className="safety-instruction">{geminiSummary.instruction}</p>
                {geminiSummary.error && (
                  <p className="safety-error">{geminiSummary.error}</p>
                )}
              </div>
            )}
            {downloadUrl && (
              <a className="btn primary download" href={downloadUrl} download>
                Download marked video
              </a>
            )}
          </div>
        )}
      </main>

      <footer className="footer">
        <p>
          Uses{" "}
          <a href="https://cloud.google.com/vertex-ai/generative-ai">Gemini on Vertex AI</a>{" "}
          for safety reasoning, with Roboflow workflows for visual obstacle marking.
        </p>
      </footer>
    </div>
  );
}
