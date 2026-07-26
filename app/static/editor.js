const LANES = ["HH", "SN", "KK"];   // 上から表示
let grid = null;
const history = [];                 // 簡略化コマンド前のグリッドを積む（元に戻す用）

async function loadGrid() {
  grid = await (await fetch("/grid")).json();
  drawGrid();
}

function updateUndoButton() {
  document.getElementById("undo").disabled = history.length === 0;
}

// 簡略化コマンドを適用：現状を履歴に積み、サーバで変換して差し替え、譜面も更新
async function applyCommand(command) {
  history.push(JSON.parse(JSON.stringify(grid)));
  updateUndoButton();
  grid = await (await fetch("/simplify", {
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
    label.textContent = lane;
    row.appendChild(label);
    grid.lanes[lane].forEach((v, i) => {
      const cell = document.createElement("div");
      cell.className = "cell" + (v ? " on" : "") + (lane === "HH" ? " hh" : "");
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
  const svg = await (await fetch("/render", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(grid),
  })).text();
  document.getElementById("score").innerHTML = svg;
}

async function exportXml() {
  const res = await fetch("/export/musicxml", {
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

async function saveGrid() {
  const msg = document.getElementById("save-msg");
  const res = await fetch("/save-grid", {
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

function togglePlay() {
  const audio = document.getElementById("audio");
  if (audio.paused) audio.play(); else audio.pause();
}

document.getElementById("render").addEventListener("click", renderScore);
document.getElementById("export").addEventListener("click", exportXml);
document.getElementById("save").addEventListener("click", saveGrid);
document.getElementById("play").addEventListener("click", togglePlay);
document.getElementById("thin_kicks").addEventListener("click", () => applyCommand("thin_kicks"));
document.getElementById("thin_hihat").addEventListener("click", () => applyCommand("thin_hihat"));
document.getElementById("undo").addEventListener("click", undo);
loadGrid();
