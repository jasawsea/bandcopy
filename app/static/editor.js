const LANES = ["HH", "SN", "KK"];   // 上から表示
let grid = null;

async function loadGrid() {
  grid = await (await fetch("/grid")).json();
  drawGrid();
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

function togglePlay() {
  const audio = document.getElementById("audio");
  if (audio.paused) audio.play(); else audio.pause();
}

document.getElementById("render").addEventListener("click", renderScore);
document.getElementById("export").addEventListener("click", exportXml);
document.getElementById("play").addEventListener("click", togglePlay);
loadGrid();
