export const EMPTY_LIVE_STATE = {
  session_id: null, revision: 0, connection: "waiting", capture: "waiting",
  source: null, analysis_enabled: false, roi: null, dimensions: null,
  model: { state: "loading", name: "yolo11n", device: "cpu", error: null },
  metrics: {}, message: null,
};

export function validRoi(roi) {
  return Array.isArray(roi) && roi.length === 4 && roi.every(Number.isFinite)
    && roi[0] >= 0 && roi[1] >= 0 && roi[2] >= 0.02 && roi[3] >= 0.02
    && roi[0] + roi[2] <= 1.000001 && roi[1] + roi[3] <= 1.000001;
}

export function pointerRoi(start, end) {
  return [Math.min(start[0], end[0]), Math.min(start[1], end[1]),
    Math.abs(start[0] - end[0]), Math.abs(start[1] - end[1])];
}

export function sameFrameContext(frame, state) {
  return frame.session_id === state.session_id && frame.revision === state.revision
    && state.connection === "connected" && state.capture === "receiving";
}

export function invalidatesDisplay(previous, next) {
  return previous.session_id !== next.session_id || previous.revision !== next.revision
    || previous.connection !== next.connection || previous.capture !== next.capture
    || previous.analysis_enabled !== next.analysis_enabled
    || previous.model?.state !== next.model?.state
    || String(previous.dimensions) !== String(next.dimensions);
}

export function metric(value, digits = 1, suffix = "") {
  return Number.isFinite(value) ? `${value.toFixed(digits)}${suffix}` : "—";
}
