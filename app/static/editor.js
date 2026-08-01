// レーン定義はサーバ(app/lanes.py)が単一ソース。editor.html が window.BANDCOPY_LANES に埋め込む
const LANE_SPECS = window.BANDCOPY_LANES || [];
const LANES = LANE_SPECS.map((s) => s.key);            // 上から表示
const LANE_LABELS = Object.fromEntries(LANE_SPECS.map((s) => [s.key, s.label]));
const LANE_CSS = Object.fromEntries(LANE_SPECS.map((s) => [s.key, s.css]));
let grid = null;
const history = [];                 // 簡略化コマンド前のグリッドを積む（元に戻す用）

let audioCtx = null;
let playTimers = [];
let playing = false;
let noiseBuffer = null;       // ctx毎に1回だけ作る白色雑音バッファ（SN/HHで共有）
let noiseBufferCtx = null;    // どのAudioContext用に作ったバッファか

// キック/タム共通：減衰する正弦波を1発鳴らす（周波数だけレーンごとに変える）
function playDecayingSine(ctx, time, f0, f1, dur) {
  const osc = ctx.createOscillator();
  const gain = ctx.createGain();
  osc.type = "sine";
  osc.frequency.setValueAtTime(f0, time);
  osc.frequency.exponentialRampToValueAtTime(f1, time + dur);
  gain.gain.setValueAtTime(1, time);
  gain.gain.exponentialRampToValueAtTime(0.001, time + dur);
  osc.connect(gain).connect(ctx.destination);
  osc.start(time); osc.stop(time + dur);
}

function getNoiseBuffer(ctx) {
  // 長さはSN/HHの最大想定デュレーション（0.15秒）を確保し、短い方は先頭を使う
  if (noiseBuffer && noiseBufferCtx === ctx) return noiseBuffer;
  const bufferSize = Math.max(1, Math.floor(ctx.sampleRate * 0.15));
  const buffer = ctx.createBuffer(1, bufferSize, ctx.sampleRate);
  const data = buffer.getChannelData(0);
  for (let i = 0; i < bufferSize; i++) data[i] = Math.random() * 2 - 1;
  noiseBuffer = buffer;
  noiseBufferCtx = ctx;
  return buffer;
}

function synthHit(lane, time) {
  const ctx = audioCtx;
  if (lane === "KK") {
    playDecayingSine(ctx, time, 120, 40, 0.15);
  } else if (lane === "SN" || lane === "HH") {
    const dur = lane === "SN" ? 0.15 : 0.05;
    const noise = ctx.createBufferSource();
    noise.buffer = getNoiseBuffer(ctx);
    const filter = ctx.createBiquadFilter();
    filter.type = lane === "SN" ? "bandpass" : "highpass";
    filter.frequency.value = lane === "SN" ? 1800 : 8000;
    const gain = ctx.createGain();
    gain.gain.setValueAtTime(1, time);
    gain.gain.exponentialRampToValueAtTime(0.001, time + dur);
    noise.connect(filter).connect(gain).connect(ctx.destination);
    noise.start(time); noise.stop(time + dur);
  } else {
    const freqMap = { HT: 220, MT: 180, FT: 140 };
    const f0 = freqMap[lane] || 160;
    playDecayingSine(ctx, time, f0, f0 * 0.6, 0.2);
  }
}

function playGrid() {
  if (playing || !grid) return;
  audioCtx = audioCtx || new (window.AudioContext || window.webkitAudioContext)();
  playing = true;
  document.getElementById("play_grid").disabled = true;
  document.getElementById("stop_grid").disabled = false;
  const spb = grid.steps_per_bar;
  const n = grid.bars * spb;
  const stepSec = (60 / grid.tempo) / (spb / 4);
  const startTime = audioCtx.currentTime + 0.05;
  for (const lane of Object.keys(grid.lanes)) {
    grid.lanes[lane].forEach((v, i) => {
      if (v && i < n) synthHit(lane, startTime + i * stepSec);
    });
  }
  const totalMs = (n * stepSec + 0.3) * 1000;
  playTimers.push(setTimeout(stopGrid, totalMs));
}

function stopGrid() {
  playTimers.forEach(clearTimeout);
  playTimers = [];
  if (audioCtx) { audioCtx.close(); audioCtx = null; }
  playing = false;
  document.getElementById("play_grid").disabled = false;
  document.getElementById("stop_grid").disabled = true;
}

async function loadGrid() {
  grid = await (await fetch("grid")).json();
  drawGrid();
}

function updateUndoButton() {
  document.getElementById("undo").disabled = history.length === 0;
}

// 簡略化コマンドを適用：現状を履歴に積み、サーバで変換して差し替え、譜面も更新
async function applyCommand(command) {
  history.push(JSON.parse(JSON.stringify(grid)));
  updateUndoButton();
  grid = await (await fetch("simplify", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ command, grid }),
  })).json();
  drawGrid();
  renderScore();
}

function undo() {
  if (history.length === 0) return;
  grid = history.pop();
  updateUndoButton();
  drawGrid();
  renderScore();
}

function drawGrid() {
  const root = document.getElementById("grid");
  root.innerHTML = "";
  const spb = grid.steps_per_bar;
  for (const lane of LANES) {
    const row = document.createElement("div");
    row.className = "lane";
    const label = document.createElement("div");
    label.className = "lane-label";
    label.textContent = LANE_LABELS[lane] || lane;
    row.appendChild(label);
    grid.lanes[lane].forEach((v, i) => {
      const cell = document.createElement("div");
      const extra = LANE_CSS[lane] ? " " + LANE_CSS[lane] : "";
      cell.className = "cell" + (v ? " on" : "") + extra;
      if (i % (spb / 4) === 0) cell.classList.add("beat");  // 拍頭
      cell.addEventListener("click", () => {
        grid.lanes[lane][i] = grid.lanes[lane][i] ? 0 : 1;
        cell.classList.toggle("on");
      });
      row.appendChild(cell);
    });
    root.appendChild(row);
  }
}

async function renderScore() {
  const svg = await (await fetch("render", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(grid),
  })).text();
  document.getElementById("score").innerHTML = svg;
}

async function exportXml() {
  const res = await fetch("export/musicxml", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(grid),
  });
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = "drums.musicxml"; a.click();
  URL.revokeObjectURL(url);
}

async function exportMidi() {
  const res = await fetch("export/midi", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(grid),
  });
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = "drums.mid"; a.click();
  URL.revokeObjectURL(url);
}

async function saveGrid() {
  const msg = document.getElementById("save-msg");
  const res = await fetch("save-grid", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(grid),
  });
  if (res.ok) {
    const data = await res.json();
    msg.textContent = "✓ 保存しました: " + data.saved;
  } else {
    const data = await res.json().catch(() => ({}));
    msg.textContent = "! 保存できません: " + (data.error || res.status);
  }
}

async function reloadForNewSong() {
  if (!confirm("読み込んだ音源を破棄して最初の画面に戻ります。よろしいですか？")) return;
  await fetch("reset", { method: "POST" });
  location.reload();
}

function togglePlay() {
  const audio = document.getElementById("audio");
  if (audio.paused) audio.play(); else audio.pause();
}

async function autoDraft() {
  const btn = document.getElementById("auto_draft");
  const msg = document.getElementById("auto-msg");
  btn.disabled = true;
  msg.textContent = "解析中…";
  try {
    const res = await fetch("auto-draft", { method: "POST" });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      msg.textContent = "! " + (data.error || res.status);
      return;
    }
    history.push(JSON.parse(JSON.stringify(grid)));
    updateUndoButton();
    grid = await res.json();
    const hits = Object.values(grid.lanes).some((a) => a.some((v) => v));
    msg.textContent = hits ? "✓ 下書きを作成（元に戻せます）" : "打点を検出できませんでした";
    drawGrid();
    renderScore();
  } catch (e) {
    msg.textContent = "! 自動下書きに失敗しました";
  } finally {
    btn.disabled = false;
  }
}

document.getElementById("render").addEventListener("click", renderScore);
document.getElementById("export").addEventListener("click", exportXml);
document.getElementById("export_midi").addEventListener("click", exportMidi);
document.getElementById("save").addEventListener("click", saveGrid);
document.getElementById("reload").addEventListener("click", reloadForNewSong);
document.getElementById("play").addEventListener("click", togglePlay);
document.getElementById("thin_kicks").addEventListener("click", () => applyCommand("thin_kicks"));
document.getElementById("thin_hihat").addEventListener("click", () => applyCommand("thin_hihat"));
document.getElementById("undo").addEventListener("click", undo);
document.getElementById("auto_draft").addEventListener("click", autoDraft);
document.getElementById("play_grid").addEventListener("click", playGrid);
document.getElementById("stop_grid").addEventListener("click", stopGrid);
loadGrid();
