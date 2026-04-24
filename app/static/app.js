const STATUS_INTERVAL_MS = 10_000;
const HISTORY_INTERVAL_MS = 60_000;
const OUTAGES_INTERVAL_MS = 60_000;

let latencyChart = null;
let currentHours = 24;

const fmtDuration = (sec) => {
  if (sec < 60) return `${sec}s`;
  if (sec < 3600) return `${Math.floor(sec / 60)}m ${sec % 60}s`;
  if (sec < 86400) return `${Math.floor(sec / 3600)}h ${Math.floor((sec % 3600) / 60)}m`;
  const d = Math.floor(sec / 86400);
  const h = Math.floor((sec % 86400) / 3600);
  return `${d}d ${h}h`;
};

const fmtTime = (ts) => {
  const d = new Date(ts * 1000);
  return d.toLocaleString();
};

async function fetchJson(url) {
  const r = await fetch(url, { cache: "no-store" });
  if (!r.ok) throw new Error(`${url} -> ${r.status}`);
  return r.json();
}

async function refreshStatus() {
  try {
    const data = await fetchJson("/api/status");
    const byTarget = Object.fromEntries(data.targets.map((t) => [t.target, t]));

    document.querySelectorAll(".card[data-target]").forEach((card) => {
      const name = card.dataset.target;
      const t = byTarget[name];
      const dot = card.querySelector(".card-dot");
      const lat = card.querySelector(".card-latency");
      const meth = card.querySelector(".card-method");
      if (!t) {
        dot.className = "card-dot dot-unknown";
        lat.textContent = "—";
        meth.textContent = "no data";
        return;
      }
      const stale = data.now - t.last_seen > 90;
      dot.className = "card-dot " + (stale ? "dot-unknown" : t.ok ? "dot-up" : "dot-down");
      lat.textContent = t.latency_ms != null ? `${t.latency_ms.toFixed(1)} ms` : "—";
      meth.textContent = t.method + (stale ? " · stale" : "");
    });

    document.getElementById("up-for").textContent = fmtDuration(data.up_for_sec);
    const fmtPct = (obj) => {
      const vals = Object.values(obj);
      if (!vals.length) return "—";
      const avg = vals.reduce((a, b) => a + b, 0) / vals.length;
      return `${avg.toFixed(2)}%`;
    };
    document.getElementById("up-24").textContent = fmtPct(data.uptime_24h);
    document.getElementById("up-7d").textContent = fmtPct(data.uptime_7d);
    document.getElementById("last-poll").textContent =
      `last poll: ${new Date().toLocaleTimeString()}`;
  } catch (e) {
    console.error("status refresh failed", e);
  }
}

const TARGET_COLORS = {
  google:     "#58a6ff",
  cloudflare: "#f78166",
  gateway:    "#3fb950",
};
const fallbackColors = ["#a371f7", "#d29922", "#db61a2", "#56d4dd"];
let _fbi = 0;
const colorFor = (name) =>
  TARGET_COLORS[name] || (TARGET_COLORS[name] = fallbackColors[_fbi++ % fallbackColors.length]);

async function refreshHistory() {
  try {
    const data = await fetchJson(`/api/history?hours=${currentHours}`);
    const datasets = Object.entries(data.series).map(([name, points]) => ({
      label: name,
      data: points.map((p) => ({ x: p.ts * 1000, y: p.latency_ms })),
      borderColor: colorFor(name),
      backgroundColor: colorFor(name),
      tension: 0.2,
      spanGaps: false,
      pointRadius: 0,
      borderWidth: 1.5,
    }));

    if (!latencyChart) {
      const ctx = document.getElementById("latency-chart").getContext("2d");
      latencyChart = new Chart(ctx, {
        type: "line",
        data: { datasets },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          animation: false,
          interaction: { mode: "nearest", intersect: false },
          scales: {
            x: { type: "time", grid: { color: "#222831" }, ticks: { color: "#8b949e" } },
            y: {
              beginAtZero: true,
              title: { display: true, text: "ms", color: "#8b949e" },
              grid: { color: "#222831" },
              ticks: { color: "#8b949e" },
            },
          },
          plugins: {
            legend: { labels: { color: "#e6edf3" } },
            tooltip: {
              callbacks: {
                label: (ctx) =>
                  `${ctx.dataset.label}: ${ctx.parsed.y == null ? "FAIL" : ctx.parsed.y.toFixed(1) + " ms"}`,
              },
            },
          },
        },
      });
    } else {
      latencyChart.data.datasets = datasets;
      latencyChart.update();
    }
  } catch (e) {
    console.error("history refresh failed", e);
  }
}

async function refreshOutages() {
  try {
    const data = await fetchJson("/api/outages?days=7");
    const tbody = document.querySelector("#outages-table tbody");
    tbody.innerHTML = "";
    if (data.outages.length === 0) {
      document.getElementById("no-outages").hidden = false;
      document.getElementById("outages-table").hidden = true;
      return;
    }
    document.getElementById("no-outages").hidden = true;
    document.getElementById("outages-table").hidden = false;
    data.outages
      .slice()
      .reverse()
      .forEach((o) => {
        const tr = document.createElement("tr");
        tr.innerHTML = `
          <td>${fmtTime(o.start)}</td>
          <td>${fmtTime(o.end)}</td>
          <td>${fmtDuration(o.duration_sec)}</td>
          <td class="cls-${o.classification}">${o.classification.toUpperCase()}</td>
        `;
        tbody.appendChild(tr);
      });
  } catch (e) {
    console.error("outages refresh failed", e);
  }
}

async function refreshHeatmap() {
  try {
    const data = await fetchJson("/api/heatmap?days=7");
    const days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
    const container = document.getElementById("heatmap");
    container.innerHTML = "";

    container.appendChild(makeCell("", "heatmap-label"));
    for (let h = 0; h < 24; h++) {
      container.appendChild(makeCell(h % 3 === 0 ? `${h}` : "", "heatmap-header"));
    }

    let max = 0;
    for (const row of data.matrix) for (const v of row) if (v > max) max = v;

    days.forEach((d, i) => {
      container.appendChild(makeCell(d, "heatmap-label"));
      for (let h = 0; h < 24; h++) {
        const v = data.matrix[i][h];
        const cell = makeCell("", "heatmap-cell");
        if (v > 0) {
          const intensity = max > 0 ? v / max : 0;
          cell.style.background = `rgba(248, 81, 73, ${0.15 + 0.85 * intensity})`;
          cell.title = `${d} ${h}:00 — ${v.toFixed(1)} min outage`;
        }
        container.appendChild(cell);
      }
    });
  } catch (e) {
    console.error("heatmap refresh failed", e);
  }
}

function makeCell(text, cls) {
  const el = document.createElement("div");
  el.className = cls;
  el.textContent = text;
  return el;
}

document.getElementById("hist-range").addEventListener("change", (e) => {
  currentHours = parseInt(e.target.value, 10);
  document.getElementById("hist-hours").textContent = currentHours;
  refreshHistory();
});

refreshStatus();
refreshHistory();
refreshOutages();
refreshHeatmap();
setInterval(refreshStatus, STATUS_INTERVAL_MS);
setInterval(refreshHistory, HISTORY_INTERVAL_MS);
setInterval(refreshOutages, OUTAGES_INTERVAL_MS);
setInterval(refreshHeatmap, OUTAGES_INTERVAL_MS);
