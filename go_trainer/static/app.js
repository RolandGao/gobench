"use strict";

const COLUMNS = "ABCDEFGHJKLMNOPQRST";
const SVG_NS = "http://www.w3.org/2000/svg";
const VIEW = 1000;
const MARGIN = 70;

const $ = (id) => document.getElementById(id);
let state = null;
let networks = [];
let hoverMove = null;
let ui = loadUi();

function loadUi() {
  try {
    return Object.assign({ teacher: true, mode: "loss" }, JSON.parse(localStorage.getItem("go-trainer-ui")));
  } catch (e) {
    return { teacher: true, mode: "loss" };
  }
}

function saveUi() {
  try { localStorage.setItem("go-trainer-ui", JSON.stringify(ui)); } catch (e) { /* private mode */ }
}

// ---- helpers -------------------------------------------------------------

// Moves are graded by points lost or by win-rate percentage points lost.
// Policy mode only changes the board overlay; grades then use points.
const METRICS = {
  loss: { key: "loss", scale: 1, unit: " pts", short: "", cuts: [0.5, 1.5, 3, 6] },
  win: { key: "win_loss", scale: 100, unit: "% win", short: "%", cuts: [1, 3, 7, 15] },
};
const TIER_NAMES = ["great", "good", "inaccuracy", "mistake", "blunder"];

function metric() { return METRICS[ui.mode] || METRICS.loss; }

function lossOf(info) {
  const m = metric();
  return info[m.key] * m.scale;
}

function tierOf(value) {
  const index = metric().cuts.findIndex((cut) => value <= cut);
  return index < 0 ? 4 : index;
}

function lossColor(value) { return `var(--g${tierOf(value)})`; }

function lossLabel(value) { return TIER_NAMES[tierOf(value)]; }

// Teacher values are from Black's side; these give them from yours.
function yourWin(blackWinrate) { return state.human === "B" ? blackWinrate : 1 - blackWinrate; }
function yourLead(blackScore) { return state.human === "B" ? blackScore : -blackScore; }
function fmtPct(p) { return `${(p * 100).toFixed(0)}%`; }
function fmtSigned(x) { return `${x >= 0 ? "+" : "−"}${Math.abs(x).toFixed(1)}`; }

function colorName(c) { return c === "B" ? "Black" : "White"; }

function fmtLoss(loss) {
  if (loss < 0.05) return "0";
  return loss < 10 ? loss.toFixed(1) : Math.round(loss).toString();
}

function fmtMinus(loss) {
  const text = fmtLoss(loss);
  return text === "0" ? "0" : `−${text}`;
}

function fmtLead(score) {
  const side = score >= 0 ? "B" : "W";
  return `${side}+${Math.abs(score).toFixed(1)}`;
}

function el(name, attrs, parent) {
  const node = document.createElementNS(SVG_NS, name);
  for (const [key, value] of Object.entries(attrs || {})) node.setAttribute(key, value);
  if (parent) parent.appendChild(node);
  return node;
}

function geometry() {
  const size = state.size;
  const cell = (VIEW - 2 * MARGIN) / (size - 1);
  return { size, cell, pos: (i) => MARGIN + i * cell };
}

function moveName(x, y) { return COLUMNS[x] + (state.size - y); }

function moveXY(move) {
  return { x: COLUMNS.indexOf(move[0]), y: state.size - parseInt(move.slice(1), 10) };
}

async function api(path, body) {
  const response = await fetch(path, {
    method: body === undefined ? "GET" : "POST",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || response.statusText);
  return data;
}

async function act(path, body) {
  try {
    setState(await api(path, body || {}));
  } catch (error) {
    $("error").hidden = false;
    $("error").textContent = error.message;
  }
}

// ---- board ---------------------------------------------------------------

function currentAnalysis() {
  if (!state) return null;
  const analysis = state.analyses[state.moves.length];
  return analysis && !analysis.error ? analysis : null;
}

function myTurn() {
  return state && !state.over && !state.thinking && state.to_move === state.human && !state.status;
}

function drawBoard() {
  const svg = $("board");
  svg.innerHTML = "";
  const { size, cell, pos } = geometry();

  const defs = el("defs", {}, svg);
  const black = el("radialGradient", { id: "stone-b", cx: "35%", cy: "30%", r: "70%" }, defs);
  el("stop", { offset: "0%", "stop-color": "#5a5855" }, black);
  el("stop", { offset: "100%", "stop-color": "#111" }, black);
  const white = el("radialGradient", { id: "stone-w", cx: "35%", cy: "30%", r: "75%" }, defs);
  el("stop", { offset: "0%", "stop-color": "#ffffff" }, white);
  el("stop", { offset: "100%", "stop-color": "#cfcac0" }, white);

  el("rect", { x: 0, y: 0, width: VIEW, height: VIEW, fill: "var(--wood)" }, svg);
  for (let i = 0; i < size; i++) {
    el("line", { x1: pos(0), y1: pos(i), x2: pos(size - 1), y2: pos(i), stroke: "var(--wood-line)", "stroke-width": 2 }, svg);
    el("line", { x1: pos(i), y1: pos(0), x2: pos(i), y2: pos(size - 1), stroke: "var(--wood-line)", "stroke-width": 2 }, svg);
    const label = { fill: "var(--wood-line)", "font-size": 26, "text-anchor": "middle", "font-family": "-apple-system, sans-serif", opacity: 0.75 };
    el("text", { ...label, x: pos(i), y: MARGIN / 2 + 4 }, svg).textContent = COLUMNS[i];
    el("text", { ...label, x: pos(i), y: VIEW - MARGIN / 2 + 14 }, svg).textContent = COLUMNS[i];
    el("text", { ...label, x: MARGIN / 2 - 8, y: pos(i) + 9 }, svg).textContent = size - i;
    el("text", { ...label, x: VIEW - MARGIN / 2 + 8, y: pos(i) + 9 }, svg).textContent = size - i;
  }
  for (const [x, y] of [[2, 2], [6, 2], [2, 6], [6, 6], [4, 4]]) {
    el("circle", { cx: pos(x), cy: pos(y), r: 7, fill: "var(--wood-line)" }, svg);
  }

  // Stones.
  state.board.forEach((stone, index) => {
    if (!stone) return;
    const x = index % size, y = Math.floor(index / size);
    el("circle", { cx: pos(x) + 3, cy: pos(y) + 4, r: cell * 0.47, fill: "rgba(0,0,0,0.25)" }, svg);
    el("circle", { cx: pos(x), cy: pos(y), r: cell * 0.47, fill: stone === 1 ? "url(#stone-b)" : "url(#stone-w)", stroke: stone === 1 ? "#000" : "#9a958c", "stroke-width": 1 }, svg);
  });

  // Last move marker.
  const last = state.moves[state.moves.length - 1];
  if (last && last[1] !== "pass") {
    const { x, y } = moveXY(last[1]);
    el("circle", { cx: pos(x), cy: pos(y), r: cell * 0.17, fill: "none", stroke: last[0] === "B" ? "#fff" : "#111", "stroke-width": 4 }, svg);
  }

  // Teacher overlay.
  const analysis = currentAnalysis();
  if (ui.teacher && analysis && myTurn()) {
    for (const [move, info] of Object.entries(analysis.moves)) {
      if (move === "pass") continue;
      const { x, y } = moveXY(move);
      const group = el("g", { "pointer-events": "none" }, svg);
      if (ui.mode !== "policy") {
        el("circle", { cx: pos(x), cy: pos(y), r: cell * 0.3, fill: lossColor(lossOf(info)), opacity: 0.9 }, group);
        el("text", { x: pos(x), y: pos(y) + 8, "text-anchor": "middle", "font-size": 23, "font-weight": 600, fill: "#1f1d1a", "font-family": "-apple-system, sans-serif" }, group).textContent = fmtLoss(lossOf(info));
      } else if (info.policy >= 0.01) {
        const strength = Math.min(1, 0.25 + info.policy * 1.5);
        el("circle", { cx: pos(x), cy: pos(y), r: cell * 0.3, fill: "var(--accent)", opacity: strength }, group);
        el("text", { x: pos(x), y: pos(y) + 8, "text-anchor": "middle", "font-size": 22, "font-weight": 600, fill: "#fff", "font-family": "-apple-system, sans-serif" }, group).textContent = Math.round(info.policy * 100);
      }
      if (move === analysis.top_policy) {
        el("circle", { cx: pos(x), cy: pos(y), r: cell * 0.4, fill: "none", stroke: "#1d4fb8", "stroke-width": 5 }, group);
      }
    }
  }

  // Hover ghost stone.
  if (hoverMove && myTurn() && state.legal.includes(hoverMove)) {
    const { x, y } = moveXY(hoverMove);
    el("circle", { cx: pos(x), cy: pos(y), r: cell * 0.47, fill: state.human === "B" ? "#111" : "#fff", opacity: 0.45, "pointer-events": "none" }, svg);
  }
}

function boardPoint(event) {
  const svg = $("board");
  const rect = svg.getBoundingClientRect();
  const { size, cell } = geometry();
  const vx = ((event.clientX - rect.left) / rect.width) * VIEW;
  const vy = ((event.clientY - rect.top) / rect.height) * VIEW;
  const x = Math.round((vx - MARGIN) / cell);
  const y = Math.round((vy - MARGIN) / cell);
  if (x < 0 || y < 0 || x >= size || y >= size) return null;
  return moveName(x, y);
}

$("board").addEventListener("mousemove", (event) => {
  const move = state ? boardPoint(event) : null;
  if (move !== hoverMove) {
    hoverMove = move;
    drawBoard();
    renderHover();
  }
});
$("board").addEventListener("mouseleave", () => { hoverMove = null; drawBoard(); renderHover(); });
$("board").addEventListener("click", (event) => {
  const move = state ? boardPoint(event) : null;
  if (move && myTurn() && state.legal.includes(move)) act("/api/play", { move });
});

// ---- panel ---------------------------------------------------------------

function renderHover() {
  const analysis = currentAnalysis();
  const info = analysis && hoverMove && analysis.moves[hoverMove];
  $("hover").textContent = info && myTurn()
    ? `${hoverMove}: ${fmtMinus(info.loss)} pts, ${fmtMinus(info.win_loss * 100)}% win → ` +
      `you'd have ${fmtPct(info.win)} win, lead ${fmtSigned(info.score)} · policy ${(info.policy * 100).toFixed(1)}%`
    : "";
}

function renderStatus() {
  let status;
  if (state.over) {
    status = `Game over: ${state.result}`;
  } else if (state.status) {
    status = state.status;
  } else if (state.thinking) {
    status = "Opponent is thinking…";
  } else if (state.to_move === state.human) {
    status = `Your move (${colorName(state.human)})`;
  } else {
    status = "Opponent to move";
  }
  $("status").textContent = status;
  const area = state.area_score;
  const caps = state.captures;
  $("substatus").textContent =
    `Komi ${state.komi} · captures B ${caps.B} / W ${caps.W} · ` +
    `Tromp-Taylor count now: ${area === 0 ? "even" : fmtLead(area)}`;
  $("error").hidden = !state.error;
  $("error").textContent = state.error;

  const analysis = currentAnalysis();
  const passInfo = analysis && analysis.moves.pass;
  $("pass").textContent = ui.teacher && passInfo && myTurn() ? `Pass (${fmtMinus(lossOf(passInfo))}${metric().short})` : "Pass";
  $("pass").disabled = !myTurn();
  $("undo").disabled = !state.moves.some(([c]) => c === state.human);
  $("toggle-teacher").textContent = ui.teacher ? "Hide teacher" : "Show teacher";
  document.body.classList.toggle("hidden-teacher", !ui.teacher);

  const downloads = Object.entries(state.downloads);
  $("download").hidden = downloads.length === 0;
  if (downloads.length) {
    const [name, d] = downloads[0];
    const pct = Math.floor((d.done / d.total) * 100);
    $("download-fill").style.width = `${pct}%`;
    $("download-text").textContent = d.error ? `Download failed: ${d.error}` : `Downloading ${name} — ${pct}% of ${(d.total / 1e6).toFixed(0)} MB`;
  }
}

function renderTeacher() {
  const root = state.analyses[state.moves.length];
  const lastMove = state.moves[state.moves.length - 1];
  $("bar-caption").textContent = lastMove
    ? `Position now, after ${lastMove[0] === state.human ? "your" : "opponent's"} ${lastMove[1]}:`
    : "Position now:";
  if (root && !root.error) {
    $("winbar-black").style.width = `${(root.winrate * 100).toFixed(1)}%`;
    $("win-text").textContent = `Black ${(root.winrate * 100).toFixed(0)}% · White ${((1 - root.winrate) * 100).toFixed(0)}%`;
    $("score-text").textContent = `Lead ${fmtLead(root.score)}`;
  } else {
    $("win-text").textContent = root && root.error ? root.error : "Evaluating…";
    $("score-text").textContent = "";
  }
  document.querySelectorAll("#overlay-mode button").forEach((b) => b.classList.toggle("active", b.dataset.mode === ui.mode));

  // Feedback on your most recent move.
  const feedback = $("feedback");
  feedback.innerHTML = "";
  let ply = -1;
  for (let i = state.moves.length - 1; i >= 0; i--) {
    if (state.moves[i][0] === state.human) { ply = i; break; }
  }
  const before = ply >= 0 ? state.analyses[ply] : null;
  if (ply < 0) {
    feedback.textContent = myTurn() && root && !root.error ? `Teacher's pick: ${root.top_policy} (ringed)` : "";
  } else if (!before || before.error) {
    feedback.textContent = "Grading your move…";
  } else {
    const move = state.moves[ply][1];
    const info = before.moves[move];
    if (info) {
      const tag = document.createElement("span");
      tag.className = "tag";
      tag.style.background = lossColor(lossOf(info));
      tag.textContent = `${lossLabel(lossOf(info))} ${fmtMinus(lossOf(info))}${metric().unit}`;
      feedback.append(`Your ${move}: `, tag);
      if (move !== before.top_policy) feedback.append(` · teacher's pick was ${before.top_policy}`);
      // Spell out the evaluation before and after your move, and after the
      // reply, since the bar above already shows the position after the reply.
      const lines = [
        `Before it: your win ${fmtPct(yourWin(before.winrate))}, lead ${fmtSigned(yourLead(before.score))}`,
        `After it: your win ${fmtPct(info.win)}, lead ${fmtSigned(info.score)}`,
      ];
      const reply = state.moves[ply + 1];
      const afterReply = state.analyses[ply + 2];
      if (reply && afterReply && !afterReply.error) {
        lines.push(
          `After opponent's ${reply[1]}: your win ${fmtPct(yourWin(afterReply.winrate))}, ` +
          `lead ${fmtSigned(yourLead(afterReply.score))}`
        );
      }
      for (const line of lines) {
        const div = document.createElement("div");
        div.className = "muted small";
        div.textContent = line;
        feedback.append(div);
      }
    }
  }

  // Legend for the current grading metric.
  const m = metric();
  $("legend").innerHTML = "";
  m.cuts.concat([null]).forEach((cut, i) => {
    const span = document.createElement("span");
    const dot = document.createElement("i");
    dot.style.background = `var(--g${i})`;
    span.append(dot, cut === null ? `>${m.cuts[3]}${m.unit}` : `≤${cut}`);
    $("legend").append(span);
  });

  // Summary of your moves this game.
  const losses = [];
  state.moves.forEach(([color, move], i) => {
    const a = state.analyses[i];
    if (color === state.human && a && a.moves && a.moves[move]) losses.push(lossOf(a.moves[move]));
  });
  if (losses.length) {
    const total = losses.reduce((s, x) => s + x, 0);
    const count = (min) => losses.filter((x) => x > min).length;
    const [, good, inaccuracy, mistake] = m.cuts;
    $("summary").textContent =
      `Your ${losses.length} moves: avg −${(total / losses.length).toFixed(2)}${m.unit} · ` +
      `${count(good) - count(inaccuracy)} inaccuracies, ${count(inaccuracy) - count(mistake)} mistakes, ` +
      `${count(mistake)} blunders`;
  } else {
    $("summary").textContent = "";
  }
}

function renderMoves() {
  const list = $("moves");
  const atBottom = list.scrollTop + list.clientHeight >= list.scrollHeight - 4;
  list.innerHTML = "";
  state.moves.forEach(([color, move], i) => {
    const li = document.createElement("li");
    const num = document.createElement("span");
    num.className = "num";
    num.textContent = `${i + 1}.`;
    const text = document.createElement("span");
    text.textContent = `${color === "B" ? "●" : "○"} ${move}`;
    if (color === state.human) text.className = "mine";
    li.append(num, text);
    const a = state.analyses[i];
    const info = a && a.moves && a.moves[move];
    if (info) {
      const loss = document.createElement("span");
      loss.className = "loss";
      loss.style.background = lossColor(lossOf(info));
      loss.textContent = `${fmtMinus(lossOf(info))}${metric().short}`;
      li.append(loss);
    }
    list.append(li);
  });
  if (atBottom) list.scrollTop = list.scrollHeight;
}

function renderControls() {
  const s = state.settings;
  if (document.activeElement !== $("opponent") && networks.length) $("opponent").value = s.opponent;
  if (document.activeElement !== $("komi")) $("komi").value = s.komi;
  document.querySelectorAll("#color button").forEach((b) => b.classList.toggle("active", b.dataset.color === selectedColor));
}

let selectedColor = "B";
let controlsInitialized = false;

function setState(next) {
  state = next;
  if (!controlsInitialized) {
    selectedColor = state.settings.color;
    controlsInitialized = true;
    renderControls();
  }
  drawBoard();
  renderStatus();
  renderTeacher();
  renderMoves();
  renderHover();
  document.querySelectorAll("#color button").forEach((b) => b.classList.toggle("active", b.dataset.color === selectedColor));
}

async function loadNetworks() {
  networks = await api("/api/networks");
  const select = $("opponent");
  select.innerHTML = "";
  networks.sort((a, b) => a.elo - b.elo);
  for (const n of networks) {
    const option = document.createElement("option");
    option.value = n.name;
    const arch = n.name.split("-")[1];
    const size = n.size >= 1e8 ? `${(n.size / 1e6).toFixed(0)} MB` : `${(n.size / 1e6).toFixed(1)} MB`;
    option.textContent = `${n.downloaded ? "✓ " : ""}Elo ${Math.round(n.elo)} · ${arch} · ${n.name.split("-").slice(2).join("-")}${n.downloaded ? "" : ` (${size})`}`;
    select.append(option);
  }
  if (state) select.value = state.settings.opponent;
}

// ---- controls ------------------------------------------------------------

document.querySelectorAll("#color button").forEach((button) => {
  button.addEventListener("click", () => {
    selectedColor = button.dataset.color;
    document.querySelectorAll("#color button").forEach((b) => b.classList.toggle("active", b === button));
  });
});

document.querySelectorAll("#overlay-mode button").forEach((button) => {
  button.addEventListener("click", () => {
    ui.mode = button.dataset.mode;
    saveUi();
    if (state) setState(state);
  });
});

$("new-game").addEventListener("click", async () => {
  await act("/api/new", {
    opponent: $("opponent").value,
    color: selectedColor,
    komi: parseFloat($("komi").value),
  });
});

// Komi applies to the game in progress immediately, not just new games.
$("komi").addEventListener("change", () => {
  const komi = parseFloat($("komi").value);
  if (Number.isFinite(komi)) act("/api/komi", { komi });
});

$("pass").addEventListener("click", () => {
  if (myTurn() && confirm("Pass? Two passes in a row end the game (Tromp-Taylor: dead stones are NOT removed, so capture them first).")) {
    act("/api/play", { move: "pass" });
  }
});

$("undo").addEventListener("click", () => act("/api/undo"));

function toggleTeacher() {
  ui.teacher = !ui.teacher;
  saveUi();
  if (state) setState(state);
}
$("toggle-teacher").addEventListener("click", toggleTeacher);

document.addEventListener("keydown", (event) => {
  if (event.target.tagName === "INPUT" || event.target.tagName === "SELECT") return;
  if (event.key === "h" || event.key === "H") toggleTeacher();
  if (event.key === "u" || event.key === "U" || ((event.metaKey || event.ctrlKey) && event.key === "z")) {
    event.preventDefault();
    act("/api/undo");
  }
});

// ---- sync loop -----------------------------------------------------------

async function poll() {
  let since = -1;
  let lastDownloads = 0;
  for (;;) {
    try {
      const next = await api(`/api/state?since=${since}`);
      since = next.version;
      setState(next);
      const downloads = Object.keys(next.downloads).length;
      if (downloads !== lastDownloads) {
        lastDownloads = downloads;
        loadNetworks();  // Refresh the ✓ marks once a download finishes.
      }
    } catch (error) {
      $("status").textContent = "Lost connection to the trainer — is trainer.py still running?";
      await new Promise((resolve) => setTimeout(resolve, 2000));
    }
  }
}

loadNetworks().then(poll);
