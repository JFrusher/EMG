"use strict";

/* Receives engine frames over SSE and paints them.
 *
 * Nothing here computes anything about the signal: every number on screen was decided
 * by the engine. This file only draws, which is what keeps the renderer replaceable. */

/* The six stages are one sequential ramp, light to dark, not six arbitrary hues: the
 * chain is an ordered process and the colour says so. Every step clears 3:1 against a
 * white card, which a 1.4px trace needs to stay visible across a room. */
const STAGES = [
  { key: "raw",       title: "Raw input",               colour: "#7c8ba1", fixed: [0, 3.3] },
  { key: "notch",     title: "Notch · mains removed",   colour: "#5b7fb9", fixed: [0, 3.3] },
  { key: "bandpass",  title: "Bandpass · EMG isolated", colour: "#4272c6", fixed: null },
  { key: "rectified", title: "Rectified",               colour: "#2563eb", fixed: null },
  { key: "lowpass",   title: "Low-pass",                colour: "#1d4ed8", fixed: null },
  { key: "envelope",  title: "Envelope",                colour: "#1e3a8a", fixed: null },
];

const INK = {
  label: "#64748b",
  rule: "#e2e8f0",
  ruleSoft: "#f1f5f9",
  ok: "#16a34a",
  warn: "#d97706",
  bad: "#dc2626",
};

const el = (id) => document.getElementById(id);

const tracesCanvas = el("traces");
const tracesCtx = tracesCanvas.getContext("2d");
const gripperCanvas = el("gripper");
const gripperCtx = gripperCanvas.getContext("2d");

let frame = null;
const axisState = new Map(); // per-stage smoothed y-range, so plots do not jitter

/* ---------------------------------------------------------------- sizing */

function fitCanvas(canvas, ctx) {
  const ratio = window.devicePixelRatio || 1;
  const { width, height } = canvas.getBoundingClientRect();
  if (!width || !height) return false;

  const w = Math.round(width * ratio);
  const h = Math.round(height * ratio);
  if (canvas.width !== w || canvas.height !== h) {
    canvas.width = w;
    canvas.height = h;
  }
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  return true;
}

/* ------------------------------------------------------------- y-scaling */

function rangeFor(stage, values) {
  if (stage.fixed) return stage.fixed;

  let lo = Infinity;
  let hi = -Infinity;
  for (const v of values) {
    if (v < lo) lo = v;
    if (v > hi) hi = v;
  }
  if (!isFinite(lo) || !isFinite(hi)) return [0, 1];

  const pad = Math.max((hi - lo) * 0.12, 0.01);
  let target = [lo - pad, hi + pad];

  // Ease toward the new range: snapping every frame reads as flicker, not as data.
  const previous = axisState.get(stage.key);
  if (previous) {
    const a = 0.15;
    target = [
      previous[0] + (target[0] - previous[0]) * a,
      previous[1] + (target[1] - previous[1]) * a,
    ];
  }
  axisState.set(stage.key, target);
  return target;
}

/* --------------------------------------------------------------- drawing */

function drawTraces() {
  if (!frame || !fitCanvas(tracesCanvas, tracesCtx)) return;

  const ctx = tracesCtx;
  const { width, height } = tracesCanvas.getBoundingClientRect();
  ctx.clearRect(0, 0, width, height);

  const padX = 12;
  const rowHeight = height / STAGES.length;
  const plotWidth = width - padX * 2;

  STAGES.forEach((stage, index) => {
    const values = frame.traces[stage.key] || [];
    const top = index * rowHeight;
    const plotTop = top + 20;
    const plotHeight = rowHeight - 26;

    if (index > 0) {
      ctx.strokeStyle = INK.ruleSoft;
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(padX, top + 0.5);
      ctx.lineTo(width - padX, top + 0.5);
      ctx.stroke();
    }

    ctx.fillStyle = INK.label;
    ctx.font = "500 10px ui-monospace, Consolas, monospace";
    ctx.textAlign = "left";
    ctx.fillText(stage.title, padX, top + 14);

    if (values.length < 2) return;

    const [lo, hi] = rangeFor(stage, values);
    const span = hi - lo || 1;
    const y = (v) => plotTop + plotHeight - ((v - lo) / span) * plotHeight;

    const improvement = frame.improvements[stage.key];
    if (improvement !== undefined) {
      ctx.fillStyle = improvement >= 0 ? INK.ok : INK.warn;
      ctx.textAlign = "right";
      ctx.fillText(`${improvement >= 0 ? "+" : ""}${improvement.toFixed(1)}%`, width - padX, top + 14);
      ctx.textAlign = "left";
    }

    // Threshold guides on the envelope, where the decision is actually made.
    if (stage.key === "envelope" && frame.thresholds) {
      const level = frame.levels.envelope || 0;
      const peak = Math.max(...values);
      const scale = level > 0.01 ? peak / level : 0;
      if (scale > 0) {
        for (const [name, colour] of [["high", INK.bad], ["low", INK.warn]]) {
          const guide = y(frame.thresholds[name] * scale);
          if (guide > plotTop && guide < plotTop + plotHeight) {
            ctx.strokeStyle = colour;
            ctx.setLineDash([3, 3]);
            ctx.lineWidth = 1;
            ctx.beginPath();
            ctx.moveTo(padX, guide);
            ctx.lineTo(width - padX, guide);
            ctx.stroke();
            ctx.setLineDash([]);
          }
        }
      }
    }

    ctx.strokeStyle = stage.colour;
    ctx.lineWidth = 1.4;
    ctx.lineJoin = "round";
    ctx.beginPath();
    for (let i = 0; i < values.length; i += 1) {
      const x = padX + (i / (values.length - 1)) * plotWidth;
      const py = y(values[i]);
      if (i === 0) ctx.moveTo(x, py);
      else ctx.lineTo(x, py);
    }
    ctx.stroke();
  });
}

/* ------------------------------------------------------------- the hand
 *
 * Two electrodes give one degree of freedom, so every joint here is driven by the same
 * closure figure. The previous version drew that one number as five separate bars,
 * which invited the reader to look for five things and offered one. A hand closing onto
 * an object says the same thing once, and says it to someone who has never seen an EMG
 * trace: the muscle moved the machine.
 *
 * Drawn side-on in hand units (palm width = 1) and mapped onto the canvas, so the
 * geometry can be reasoned about without carrying pixel arithmetic around. */

/* Canvas angles run clockwise with y pointing down, so -PI/2 is straight up. The
 * fingers sit to the right of the thumb, which means they must rotate anticlockwise —
 * negative bend — to close onto it. Getting that sign backwards curls them away from
 * the thumb and the hand reads as a crab. */
const HAND = {
  palm: { x: 0.0, y: 0.0, w: 1.0, h: 1.15 },
  // Where each finger leaves the knuckle line, and the length of its three bones.
  fingers: [
    { x: 0.18, lengths: [0.44, 0.30, 0.20], width: 0.15 },
    { x: 0.44, lengths: [0.48, 0.32, 0.21], width: 0.15 },
    { x: 0.68, lengths: [0.44, 0.30, 0.20], width: 0.14 },
    { x: 0.88, lengths: [0.35, 0.24, 0.16], width: 0.12 },
  ],
  // Curl per joint at full closure, in radians. Sums to about 95 degrees — a grip,
  // not a fist.
  bend: [-0.62, -0.55, -0.45],
  thumb: { x: 0.02, y: 0.60, lengths: [0.40, 0.30], width: 0.17, bend: [0.55, 0.45] },
  thumbAngle: -Math.PI * 0.78,
  // Drawn behind the hand, so the fingers wrap in front of it. Big enough to show
  // around them — otherwise the grip has nothing visible to be a grip on.
  object: { x: -0.14, y: -0.36, w: 0.78, h: 0.90 },
  // Everything above, plus the forearm, in hand units — used to fit the canvas.
  bounds: { x0: -0.78, x1: 1.12, y0: -1.14, y1: 1.55 },
};

const CONTACT_AT = 0.30; // closure at which the fingertips reach the object

function chain(ctx, project, start, angle, lengths, bends, curl, width, colour) {
  let [x, y] = start;
  let a = angle;

  lengths.forEach((length, index) => {
    a += (bends[index] || 0) * curl;
    const nx = x + Math.cos(a) * length;
    const ny = y + Math.sin(a) * length;

    ctx.strokeStyle = colour;
    ctx.lineCap = "round";
    ctx.lineWidth = project.scale * width * (1 - index * 0.12);
    ctx.beginPath();
    ctx.moveTo(...project(x, y));
    ctx.lineTo(...project(nx, ny));
    ctx.stroke();

    x = nx;
    y = ny;
  });

  return [x, y];
}

function drawGripper() {
  if (!frame || !fitCanvas(gripperCanvas, gripperCtx)) return;

  const ctx = gripperCtx;
  const { width, height } = gripperCanvas.getBoundingClientRect();
  ctx.clearRect(0, 0, width, height);

  const grip = frame.gripper;
  const closure = Math.min(grip.force / grip.max_force, 1);
  const gripping = closure > CONTACT_AT;

  // Fit the declared hand-unit box into the canvas rather than guessing offsets.
  const b = HAND.bounds;
  const scale = Math.min(width / (b.x1 - b.x0), height / (b.y1 - b.y0)) * 0.94;
  const originX = width / 2 - ((b.x0 + b.x1) / 2) * scale;
  const originY = height / 2 - ((b.y0 + b.y1) / 2) * scale;
  const project = (x, y) => [originX + x * scale, originY + y * scale];
  project.scale = scale;

  // Tension reads as a darkening of the hand; the accent is reserved for contact.
  const limb = gripping ? "#64748b" : "#94a3b8";

  // --- the object being held ------------------------------------------------
  const squeeze = 1 - 0.1 * closure;
  const obj = HAND.object;
  const [ox, oy] = project(obj.x, obj.y);
  const ow = obj.w * scale * squeeze;
  const oh = obj.h * scale;

  ctx.fillStyle = gripping ? "#eff6ff" : "#f8fafc";
  ctx.strokeStyle = gripping ? "#2563eb" : "#cbd5e1";
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  ctx.roundRect(ox - ow / 2, oy - oh / 2, ow, oh, 4);
  ctx.fill();
  ctx.stroke();

  // --- forearm and palm -----------------------------------------------------
  ctx.strokeStyle = limb;
  ctx.lineCap = "round";
  ctx.lineWidth = scale * 0.5;
  ctx.beginPath();
  ctx.moveTo(...project(0.5, 1.5));
  ctx.lineTo(...project(0.5, 1.05));
  ctx.stroke();

  const palm = HAND.palm;
  ctx.fillStyle = limb;
  ctx.beginPath();
  ctx.roundRect(
    ...project(palm.x, palm.y),
    palm.w * scale,
    palm.h * scale,
    scale * 0.16
  );
  ctx.fill();

  // --- fingers and thumb ----------------------------------------------------
  const flex = grip.fingers || [];
  const tips = [];

  HAND.fingers.forEach((finger, index) => {
    const curl = flex[index + 1] !== undefined ? flex[index + 1] : closure;
    tips.push(
      chain(ctx, project, [finger.x, 0], -Math.PI / 2, finger.lengths,
            HAND.bend, curl, finger.width, limb)
    );
  });

  const thumb = HAND.thumb;
  const thumbCurl = flex[0] !== undefined ? flex[0] : closure;
  tips.push(
    chain(ctx, project, [thumb.x, thumb.y], HAND.thumbAngle, thumb.lengths,
          thumb.bend, thumbCurl, thumb.width, limb)
  );

  // --- contact ---------------------------------------------------------------
  if (gripping) {
    ctx.fillStyle = "#2563eb";
    for (const [tx, ty] of tips) {
      const [px, py] = project(tx, ty);
      ctx.beginPath();
      ctx.arc(px, py, scale * 0.05, 0, Math.PI * 2);
      ctx.fill();
    }
  }
}

/* ------------------------------------------------------------ DOM update */

function setText(id, text) {
  const node = el(id);
  if (node.textContent !== text) node.textContent = text;
}

/* Engine log lines arrive as "[  12.34s] message". */
const LOG_LINE = /^\[\s*([\d.]+)s\]\s*(.*)$/;

function updatePanel() {
  if (!frame) return;

  const source = frame.source;

  let health = "ok";
  if (source.failover || source.state === "reconnecting" || frame.flags.paused) health = "warn";
  if (source.state === "stopped" || source.state === "error") health = "bad";

  el("status-dot").className = `dot ${health}`;
  el("source-state").className = `chip ${health}`;

  setText("source-name", source.name);

  // Paused leads, because the source is still streaming happily and the frozen traces
  // would otherwise read as a dead input.
  const state = frame.flags.paused
    ? ["paused", source.state, source.detail]
    : [source.state, source.detail];
  setText("source-state", state.filter(Boolean).join(" · "));
  setText("session-clock", `${frame.t.toFixed(1)} s`);

  setText("tile-rate", frame.rate.measured.toFixed(0));
  setText("tile-rate-design", `/ ${frame.rate.design.toFixed(0)} Hz`);
  setText("tile-samples", frame.counts.samples.toLocaleString());
  setText("tile-events", String(frame.counts.events));
  setText("tile-cocontractions", String(frame.counts.cocontractions));

  const grip = frame.gripper;
  setText("grip-force", `${grip.force.toFixed(1)} N`);

  setText("grip-state", frame.flags.calibrating
    ? "calibrating"
    : frame.flags.calibrated ? "calibrated" : "adaptive");
  el("grip-state").className = `chip${frame.flags.calibrated ? " ok" : ""}`;

  for (const [id, name] of [["band-open", "OPEN"], ["band-light", "LIGHT"], ["band-power", "POWER"]]) {
    el(id).classList.toggle("on", grip.label === name);
  }

  el("pad-a").style.width = `${frame.levels.a * 100}%`;
  el("pad-b").style.width = `${frame.levels.b * 100}%`;
  setText("pad-a-value", frame.levels.a.toFixed(2));
  setText("pad-b-value", frame.levels.b.toFixed(2));

  const metrics = el("metrics");
  const entries = Object.entries(frame.improvements);
  if (metrics.childElementCount !== entries.length) {
    metrics.replaceChildren(
      ...entries.map(() => {
        const row = document.createElement("tr");
        const stage = document.createElement("td");
        const value = document.createElement("td");
        value.className = "num";
        row.append(stage, value);
        return row;
      })
    );
  }
  entries.forEach(([key, value], index) => {
    const row = metrics.children[index];
    row.children[0].textContent = key;
    row.children[1].textContent = `${value >= 0 ? "+" : ""}${value.toFixed(1)}%`;
    row.children[1].className = `num ${value >= 0 ? "up" : "down"}`;
  });

  const log = el("log");
  log.replaceChildren(
    ...frame.events.map((line) => {
      const match = LOG_LINE.exec(line);
      const row = document.createElement("tr");
      const time = document.createElement("td");
      const message = document.createElement("td");
      time.className = "t";
      time.textContent = match ? `${match[1]}s` : "";
      message.textContent = match ? match[2] : line;
      row.append(time, message);
      return row;
    })
  );
  setText("log-note", frame.events.length ? `${frame.events.length} recent` : "");

  el("btn-pause").textContent = frame.flags.paused ? "Resume" : "Pause";
  el("btn-calibrate").classList.toggle("active", frame.flags.calibrated);
}

/* --------------------------------------------------------------- wiring */

function send(action) {
  fetch("/command", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action }),
  }).catch(() => {
    /* the status chip already shows when the engine is unreachable */
  });
}

el("btn-pause").addEventListener("click", () => send("toggle-pause"));
el("btn-calibrate").addEventListener("click", () => send("calibrate"));
el("btn-reset").addEventListener("click", () => send("reset"));
el("btn-snapshot").addEventListener("click", () => {
  const link = document.createElement("a");
  link.download = `emg-demo-${new Date().toISOString().replace(/[:.]/g, "-")}.png`;
  link.href = tracesCanvas.toDataURL("image/png");
  link.click();
});

function toggleFullscreen() {
  if (document.fullscreenElement) document.exitFullscreen();
  else document.documentElement.requestFullscreen().catch(() => {});
}

document.addEventListener("keydown", (event) => {
  if (event.key.toLowerCase() === "f") toggleFullscreen();
  if (event.target.tagName === "BUTTON") return;
  if (event.key === " ") { event.preventDefault(); send("toggle-pause"); }
  if (event.key.toLowerCase() === "c") send("calibrate");
  if (event.key.toLowerCase() === "r") send("reset");
});

/* Browsers only grant fullscreen from a user gesture, so --fullscreen arms it and the
 * operator's first click or keypress on the stand machine takes it there. */
if (new URLSearchParams(location.search).get("fullscreen") === "1") {
  const notice = document.createElement("div");
  notice.className = "notice";
  notice.textContent = "Click anywhere, or press F, for fullscreen";
  document.body.append(notice);

  const arm = () => {
    toggleFullscreen();
    notice.remove();
    document.removeEventListener("click", arm);
    document.removeEventListener("keydown", arm);
  };
  document.addEventListener("click", arm, { once: true });
  document.addEventListener("keydown", arm, { once: true });
}

const stream = new EventSource("/stream");
stream.addEventListener("message", (event) => {
  frame = JSON.parse(event.data);
});
stream.addEventListener("error", () => {
  el("status-dot").className = "dot bad";
  el("source-state").className = "chip bad";
  setText("source-state", "stream lost — is the demo still running?");
});

function render() {
  drawTraces();
  drawGripper();
  updatePanel();
  requestAnimationFrame(render);
}
requestAnimationFrame(render);
