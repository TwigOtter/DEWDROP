"use strict";

const api = (path) => fetch(path).then((r) => r.json());
const $ = (sel) => document.querySelector(sel);
const fmt = (v, suffix = "") => (v === null || v === undefined ? "—" : v + suffix);

const PALETTE = ["#4fc3f7", "#ff7043", "#66bb6a", "#ab47bc", "#ffca28", "#26a69a"];

// ── Tab switching ──────────────────────────────────────────────────────────
const loaders = {};
let _activeView = "station";

document.querySelectorAll("#tabs button").forEach((btn) => {
  btn.addEventListener("click", () => {
    const leaving = _activeView;
    const arriving = btn.dataset.view;
    if (leaving === arriving) return;

    // Stop station auto-refresh when navigating away.
    if (leaving === "station") _stopStationTimer();

    document.querySelectorAll("#tabs button").forEach((b) => b.classList.remove("active"));
    document.querySelectorAll(".view").forEach((v) => v.classList.remove("active"));
    btn.classList.add("active");
    $("#" + arriving).classList.add("active");
    _activeView = arriving;
    if (loaders[arriving]) loaders[arriving]();
  });
});

// ── Status line ──────────────────────────────────────────────────────────---
api("/health").then((h) => {
  $("#status").textContent =
    `${h.location} · sources: ${h.sources.join(", ")} · truth: ${h.actuals.join(", ")}`;
});


// ════════════════════════════════════════════════════════════════════════════
// CURRENT CONDITIONS
// ════════════════════════════════════════════════════════════════════════════
const _stationCharts = {};
let _stationTimer = null;

function _stopStationTimer() {
  if (_stationTimer) { clearInterval(_stationTimer); _stationTimer = null; }
}

function degToCompass(deg) {
  if (deg === null || deg === undefined) return "—";
  return ["N","NE","E","SE","S","SW","W","NW"][Math.round(deg / 45) % 8];
}

function renderStationCards(live) {
  const box = $("#station-cards");
  if (!live || live.error || live.temp_out_f === undefined) {
    box.innerHTML = `<p class="empty">${live?.error || "Station not configured or unreachable. Set DEWDROP_GW2000_HOST in .env"}</p>`;
    return;
  }
  const dir = degToCompass(live.wind_dir_deg);
  const gust = live.wind_gust_mph != null ? `<div class="sc-sub">Gust ${live.wind_gust_mph} mph</div>` : "";
  const cards = [
    `<div class="sc primary">
       <div class="sc-label">Outdoor Temp</div>
       <div class="sc-val warm">${fmt(live.temp_out_f, "°F")}</div>
     </div>`,
    `<div class="sc">
       <div class="sc-label">Humidity</div>
       <div class="sc-val cool">${fmt(live.humidity_out, "%")}</div>
     </div>`,
    `<div class="sc">
       <div class="sc-label">Wind</div>
       <div class="sc-val green">${fmt(live.wind_speed_mph, " mph")} <span style="font-size:.9rem;font-weight:400">${dir}</span></div>
       ${gust}
     </div>`,
    `<div class="sc">
       <div class="sc-label">Pressure</div>
       <div class="sc-val">${fmt(live.pressure_inhg, " inHg")}</div>
     </div>`,
    `<div class="sc">
       <div class="sc-label">Daily Precip</div>
       <div class="sc-val">${fmt(live.precip_daily_mm, " mm")}</div>
     </div>`,
    `<div class="sc">
       <div class="sc-label">UV Index</div>
       <div class="sc-val">${fmt(live.uv_index)}</div>
     </div>`,
    live.temp_in_f != null
      ? `<div class="sc"><div class="sc-label">Indoor Temp</div><div class="sc-val">${fmt(live.temp_in_f, "°F")}</div></div>`
      : "",
    live.humidity_in != null
      ? `<div class="sc"><div class="sc-label">Indoor Humidity</div><div class="sc-val">${fmt(live.humidity_in, "%")}</div></div>`
      : "",
    live.solar_rad_wm2 != null
      ? `<div class="sc"><div class="sc-label">Solar</div><div class="sc-val">${fmt(live.solar_rad_wm2, " W/m²")}</div></div>`
      : "",
  ];
  box.innerHTML = cards.join("");
}

function _makeChart(id, datasets, yLabel) {
  if (_stationCharts[id]) _stationCharts[id].destroy();
  _stationCharts[id] = new Chart(document.getElementById(id), {
    type: "line",
    data: { datasets },
    options: {
      parsing: false,
      animation: false,
      scales: {
        x: {
          type: "category",
          ticks: { color: "#8aa0b4", maxTicksLimit: 10, maxRotation: 0 },
          grid: { color: "#27384a" },
        },
        y: {
          title: { display: !!yLabel, text: yLabel, color: "#8aa0b4" },
          ticks: { color: "#8aa0b4" },
          grid: { color: "#27384a" },
        },
      },
      plugins: { legend: { display: datasets.length > 1, labels: { color: "#e8eef4", boxWidth: 12 } } },
    },
  });
}

function renderStationCharts(readings) {
  if (!readings || !readings.length) return;

  const labels = readings.map((r) => {
    const d = new Date(r.ts);
    return d.getHours().toString().padStart(2, "0") + ":" + d.getMinutes().toString().padStart(2, "0");
  });

  const line = (data, color, label, dash) => ({
    label,
    data,
    labels,
    borderColor: color,
    backgroundColor: color + "22",
    fill: !dash,
    tension: 0.25,
    pointRadius: 0,
    borderWidth: 2,
    borderDash: dash || [],
  });

  _makeChart("chart-temp",
    [line(readings.map((r) => r.temp_out_f), "#ff7043", "Temp (°F)")]);

  _makeChart("chart-humidity",
    [line(readings.map((r) => r.humidity_out), "#4fc3f7", "Humidity (%)")]);

  _makeChart("chart-wind", [
    line(readings.map((r) => r.wind_speed_mph), "#66bb6a", "Speed"),
    line(readings.map((r) => r.wind_gust_mph), "#ffca28", "Gust", [5, 3]),
  ]);

  _makeChart("chart-precip",
    [line(readings.map((r) => r.precip_daily_mm), "#ab47bc", "Precip (mm)")]);
}

async function refreshStation() {
  const [live, history] = await Promise.all([
    api("/api/station/live"),
    api("/api/station/today"),
  ]);
  renderStationCards(live);
  renderStationCharts(history.readings);
  if (live.ts) {
    const d = new Date(live.ts);
    const t = d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    $("#station-updated").textContent = `Last reading: ${t}`;
  }
}

loaders.station = async () => {
  await refreshStation();
  _stopStationTimer();
  _stationTimer = setInterval(refreshStation, 60_000);
};

$("#station-refresh-btn").addEventListener("click", refreshStation);


// ════════════════════════════════════════════════════════════════════════════
// FORECAST DASHBOARD
// ════════════════════════════════════════════════════════════════════════════
loaders.dashboard = async () => {
  const data = await api("/api/ensemble");
  const box = $("#ensemble-cards");
  if (!data.days.length) {
    box.innerHTML = '<p class="empty">No forecasts collected yet.</p>';
    return;
  }
  box.innerHTML = data.days.map((d) => `
    <div class="card">
      <div class="date">+${d.horizon_days}d · ${d.target_date}</div>
      <div class="hi">${fmt(d.temp_high_f, "°")}${d.temp_high_f_sd != null ? `<span class="band"> ±${d.temp_high_f_sd}</span>` : ""}</div>
      <div class="lo">${fmt(d.temp_low_f, "°")}${d.temp_low_f_sd != null ? `<span class="band"> ±${d.temp_low_f_sd}</span>` : ""}</div>
      <div class="band">precip ${fmt(d.precip_mm, " mm")}</div>
      <div class="cond">${d.condition || "—"}</div>
      <div class="band">${d.n_services} services</div>
    </div>`).join("");
};


// ════════════════════════════════════════════════════════════════════════════
// SERVICE COMPARISON
// ════════════════════════════════════════════════════════════════════════════
loaders.services = async () => {
  const hmin = $("#svc-hmin").value, hmax = $("#svc-hmax").value;
  const data = await api(`/api/services?horizon_min=${hmin}&horizon_max=${hmax}`);
  const tb = $("#svc-table tbody");
  tb.innerHTML = data.services.length
    ? data.services.map((s) => `<tr>
        <td>${s.service}</td><td>${fmt(s.mae_high)}</td><td>${fmt(s.mae_low)}</td>
        <td>${fmt(s.mae_precip)}</td><td>${fmt(s.condition_pct, "%")}</td><td>${s.n}</td></tr>`).join("")
    : '<tr><td colspan="6" class="empty">No scored forecasts yet.</td></tr>';
};
$("#svc-apply").addEventListener("click", () => loaders.services());


// ════════════════════════════════════════════════════════════════════════════
// BIAS CURVES
// ════════════════════════════════════════════════════════════════════════════
let biasChart = null;
loaders.bias = async () => {
  const metric = $("#bias-metric").value;
  const data = await api(`/api/bias-curves?metric=${metric}`);
  const services = Object.keys(data.curves);
  const datasets = services.map((svc, i) => ({
    label: svc,
    data: data.curves[svc].map((p) => ({ x: p.horizon_days, y: p.mean_err })),
    borderColor: PALETTE[i % PALETTE.length],
    backgroundColor: PALETTE[i % PALETTE.length],
    tension: 0.2,
  }));
  if (biasChart) biasChart.destroy();
  biasChart = new Chart($("#bias-chart"), {
    type: "line",
    data: { datasets },
    options: {
      scales: {
        x: { type: "linear", title: { display: true, text: "Horizon (days)" }, ticks: { color: "#8aa0b4" } },
        y: { title: { display: true, text: "Mean signed error" }, ticks: { color: "#8aa0b4" }, grid: { color: "#27384a" } },
      },
      plugins: { legend: { labels: { color: "#e8eef4" } } },
    },
  });
};
$("#bias-metric").addEventListener("change", () => loaders.bias());


// ════════════════════════════════════════════════════════════════════════════
// DAILY DRILL-DOWN
// ════════════════════════════════════════════════════════════════════════════
async function loadDaily() {
  const date = $("#daily-date").value;
  if (!date) return;
  const data = await api(`/api/daily/${date}`);
  $("#daily-actuals").innerHTML = data.actuals.length
    ? "<strong>Actuals:</strong> " + data.actuals.map((a) =>
        `${a.source}: ${fmt(a.temp_high_f, "°")}/${fmt(a.temp_low_f, "°")}, ${fmt(a.precip_mm, "mm")}, ${a.condition || "—"}`).join(" · ")
    : "<span class='empty'>No actuals recorded for this date.</span>";
  const tb = $("#daily-table tbody");
  tb.innerHTML = data.forecasts.length
    ? data.forecasts.map((f) => `<tr>
        <td>${f.service}</td><td>+${f.horizon_days}d</td><td>${fmt(f.temp_high_f, "°")}</td>
        <td>${fmt(f.temp_low_f, "°")}</td><td>${fmt(f.precip_mm, "mm")}</td><td>${f.condition || "—"}</td></tr>`).join("")
    : '<tr><td colspan="6" class="empty">No forecasts for this date.</td></tr>';
}
$("#daily-load").addEventListener("click", loadDaily);
loaders.daily = () => { if (!$("#daily-date").value) $("#daily-date").value = new Date().toISOString().slice(0, 10); };


// ════════════════════════════════════════════════════════════════════════════
// RAW LOG
// ════════════════════════════════════════════════════════════════════════════
loaders.raw = async () => {
  const data = await api("/api/errors?limit=200");
  const tb = $("#raw-table tbody");
  tb.innerHTML = data.errors.length
    ? data.errors.map((e) => `<tr>
        <td>${e.id}</td><td>${e.service}</td><td>${e.target_date}</td><td>+${e.horizon_days}d</td>
        <td>${e.actuals_source}</td><td>${fmt(e.temp_high_err)}</td><td>${fmt(e.temp_low_err)}</td>
        <td>${fmt(e.precip_err)}</td><td>${e.condition_match === null ? "—" : (e.condition_match ? "✓" : "✗")}</td></tr>`).join("")
    : '<tr><td colspan="9" class="empty">No error rows yet.</td></tr>';
};


// ── Initial load ───────────────────────────────────────────────────────────
loaders.station();
