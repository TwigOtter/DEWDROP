"use strict";

const api = (path) => fetch(path).then((r) => r.json());
const $ = (sel) => document.querySelector(sel);
const fmt = (v, suffix = "") => (v === null || v === undefined ? "—" : v + suffix);
// Horizon label: +2d for forecasts, 0d for same-day, -1d for snapshots
// mistakenly taken after the target day (legacy rollover bug rows).
const fmtHorizon = (h) => (h > 0 ? `+${h}d` : `${h}d`);

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

// ── Status line + staleness banner ───────────────────────────────────────---
api("/health").then((h) => {
  $("#status").textContent =
    `${h.location} · sources: ${h.sources.join(", ")} · truth: ${h.actuals.join(", ")}`;

  const stale = [];
  const feed = (f, kind) =>
    `${f.name} ${kind} ${f.last ? `last ${f.last} (${f.age_days}d ago)` : "never fetched"}`;
  (h.staleness?.forecasts || []).filter((f) => f.stale)
    .forEach((f) => stale.push(feed(f, "forecasts")));
  (h.staleness?.actuals || []).filter((f) => f.stale)
    .forEach((f) => stale.push(feed(f, "actuals")));
  const st = h.staleness?.station;
  if (st?.stale) {
    stale.push(st.last
      ? `station readings last ${new Date(st.last).toLocaleString()} (${st.age_hours}h ago)`
      : "station readings never recorded");
  }
  const banner = $("#stale-banner");
  banner.hidden = !stale.length;
  if (stale.length) banner.textContent = `⚠️ Stale data: ${stale.join(" · ")}`;
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

// NWS "feels like": wind chill below 50°F with wind, heat index above 80°F
// with humidity, plain air temperature in between.
function feelsLikeF(t, rh, wind) {
  if (t == null) return null;
  if (t <= 50 && wind != null && wind > 3) {
    const v = Math.pow(wind, 0.16);
    return 35.74 + 0.6215 * t - 35.75 * v + 0.4275 * t * v;
  }
  if (t >= 80 && rh != null) {
    // Rothfusz regression, applied when the simple estimate runs >= 80.
    const simple = 0.5 * (t + 61.0 + (t - 68.0) * 1.2 + rh * 0.094);
    if ((simple + t) / 2 < 80) return simple;
    let hi = -42.379 + 2.04901523 * t + 10.14333127 * rh
      - 0.22475541 * t * rh - 6.83783e-3 * t * t - 5.481717e-2 * rh * rh
      + 1.22874e-3 * t * t * rh + 8.5282e-4 * t * rh * rh
      - 1.99e-6 * t * t * rh * rh;
    if (rh < 13 && t <= 112) {
      hi -= ((13 - rh) / 4) * Math.sqrt((17 - Math.abs(t - 95)) / 17);
    } else if (rh > 85 && t <= 87) {
      hi += ((rh - 85) / 10) * ((87 - t) / 2);
    }
    return hi;
  }
  return t;
}

const round1 = (v) => (v == null ? null : Math.round(v * 10) / 10);

function renderStationCards(live) {
  const box = $("#station-cards");
  if (!live || live.error || live.temp_out_f === undefined) {
    box.innerHTML = `<p class="empty">${live?.error || "Station not configured or unreachable. Set DEWDROP_GW2000_HOST in .env"}</p>`;
    return;
  }
  const dir = degToCompass(live.wind_dir_deg);
  const gust = live.wind_gust_mph != null ? `<div class="sc-sub">Gust ${live.wind_gust_mph} mph</div>` : "";
  const feels = round1(feelsLikeF(live.temp_out_f, live.humidity_out, live.wind_speed_mph));
  const cards = [
    `<div class="sc primary">
       <div class="sc-label">Outdoor Temp</div>
       <div class="sc-val warm">${fmt(live.temp_out_f, "°F")}</div>
     </div>`,
    `<div class="sc">
       <div class="sc-label">Feels Like</div>
       <div class="sc-val warm">${fmt(feels, "°F")}</div>
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

function _makeChart(id, labels, datasets, yLabel) {
  if (_stationCharts[id]) _stationCharts[id].destroy();
  _stationCharts[id] = new Chart(document.getElementById(id), {
    type: "line",
    data: { labels, datasets },
    options: {
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
    borderColor: color,
    backgroundColor: color + "22",
    fill: !dash,
    tension: 0.25,
    pointRadius: 0,
    borderWidth: 2,
    borderDash: dash || [],
  });

  _makeChart("chart-temp", labels, [
    line(readings.map((r) => r.temp_out_f), "#ff7043", "Temp"),
    line(readings.map((r) => round1(feelsLikeF(r.temp_out_f, r.humidity_out, r.wind_speed_mph))),
         "#ffca28", "Feels like", [5, 3]),
  ]);

  _makeChart("chart-humidity", labels,
    [line(readings.map((r) => r.humidity_out), "#4fc3f7", "Humidity (%)")]);

  _makeChart("chart-pressure", labels,
    [line(readings.map((r) => r.pressure_inhg), "#26a69a", "Pressure (inHg)")]);

  _makeChart("chart-wind", labels, [
    line(readings.map((r) => r.wind_speed_mph), "#66bb6a", "Speed"),
    line(readings.map((r) => r.wind_gust_mph), "#ffca28", "Gust", [5, 3]),
  ]);

  _makeChart("chart-precip", labels,
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
  const [data, mc] = await Promise.all([
    api("/api/ensemble"),
    api("/api/microclimate"),
  ]);

  const banner = $("#ensemble-microclimate");
  const hOff = mc.temp_high_offset_f, lOff = mc.temp_low_offset_f;
  if (mc.n_days === 0 || (hOff === null && lOff === null)) {
    banner.innerHTML = `🏠 Backyard offset vs ${mc.regional} (${mc.window_days}d window): calibrating — ${mc.n_days} paired day(s) so far`;
  } else {
    const word = (v) => v == null ? "?" : v > 0 ? `${v.toFixed(1)}° warmer` : v < 0 ? `${(-v).toFixed(1)}° cooler` : "matches";
    banner.innerHTML = `🏠 Backyard offset vs ${mc.regional} (${mc.window_days}d · ${mc.n_days} pts): highs run ${word(hOff)}, lows ${word(lOff)}`;
  }

  const box = $("#ensemble-cards");
  _ensembleDays = data.days;
  renderEnsembleChart();
  if (!data.days.length) {
    box.innerHTML = '<p class="empty">No forecasts collected yet.</p>';
    return;
  }
  const home = (d) => {
    if (hOff == null || lOff == null) return "";
    if (d.temp_high_f == null || d.temp_low_f == null) return "";
    return `<div class="band">home: ${(d.temp_high_f + hOff).toFixed(1)}° / ${(d.temp_low_f + lOff).toFixed(1)}°</div>`;
  };
  const pm = (v, sd, unit) =>
    `${fmt(v, unit)}${sd != null ? ` ±${sd}` : ""}`;
  box.innerHTML = data.days.map((d) => `
    <div class="card">
      <div class="date">${fmtHorizon(d.horizon_days)} · ${d.target_date}</div>
      <div class="hi">${fmt(d.temp_high_f, "°")}${d.temp_high_f_sd != null ? `<span class="band"> ±${d.temp_high_f_sd}</span>` : ""}</div>
      <div class="lo">${fmt(d.temp_low_f, "°")}${d.temp_low_f_sd != null ? `<span class="band"> ±${d.temp_low_f_sd}</span>` : ""}</div>
      <div class="band">precip ${pm(d.precip_mm, d.precip_mm_sd, " mm")}</div>
      <div class="band">rain ${fmt(d.rain_chance_pct, "%")}</div>
      <div class="band">wind ${pm(d.wind_max_mph, d.wind_max_mph_sd, " mph")}</div>
      <div class="cond">${d.condition || "—"}</div>
      ${home(d)}
      <div class="band">${d.n_services} services · ${d.history_days ? `${d.history_days}d history` : "uncorrected"}</div>
    </div>`).join("");
};

// Ensemble lines with shaded ±1σ bands on a shared x-axis of target dates,
// switchable between temperature (high/low), precip and wind.
const ENSEMBLE_METRICS = {
  temp: {
    title: "High / Low with ±1σ bands", y: "°F", nonNegative: false,
    series: [["High (°F)", "temp_high_f", "#ff7043"],
             ["Low (°F)", "temp_low_f", "#4fc3f7"]],
  },
  precip_mm: {
    title: "Precipitation with ±1σ band", y: "mm", nonNegative: true,
    series: [["Precip (mm)", "precip_mm", "#ab47bc"]],
  },
  wind_max_mph: {
    title: "Max sustained wind with ±1σ band", y: "mph", nonNegative: true,
    series: [["Wind max (mph)", "wind_max_mph", "#66bb6a"]],
  },
};
let _ensembleDays = [];
let _ensembleMetric = "temp";
let ensembleChart = null;

function renderEnsembleChart() {
  if (ensembleChart) { ensembleChart.destroy(); ensembleChart = null; }
  const days = _ensembleDays;
  const cfg = ENSEMBLE_METRICS[_ensembleMetric];
  $("#ensemble-chart-title").textContent = cfg.title;
  if (!days.length) return;

  const labels = days.map((d) => `${fmtHorizon(d.horizon_days)} ${d.target_date.slice(5)}`);
  const edge = (vals, sds, sign) =>
    vals.map((v, i) => {
      if (v == null || sds[i] == null) return v;
      const e = v + sign * sds[i];
      return cfg.nonNegative ? Math.max(e, 0) : e;
    });

  const bandPair = (vals, sds, color) => [
    { label: "±band", data: edge(vals, sds, 1), borderWidth: 0, pointRadius: 0, fill: false },
    { label: "±band", data: edge(vals, sds, -1), borderWidth: 0, pointRadius: 0,
      backgroundColor: color + "2e", fill: "-1" },
  ];
  const line = (label, vals, color) => ({
    label, data: vals, borderColor: color, backgroundColor: color,
    tension: 0.25, pointRadius: 3, borderWidth: 2, fill: false,
  });

  const datasets = cfg.series.flatMap(([label, key, color]) => {
    const vals = days.map((d) => d[key]);
    const sds = days.map((d) => d[key + "_sd"]);
    return [...bandPair(vals, sds, color), line(label, vals, color)];
  });

  ensembleChart = new Chart(document.getElementById("ensemble-chart"), {
    type: "line",
    data: { labels, datasets },
    options: {
      animation: false,
      spanGaps: true,
      scales: {
        x: { ticks: { color: "#8aa0b4", maxRotation: 0 }, grid: { color: "#27384a" } },
        y: { title: { display: true, text: cfg.y, color: "#8aa0b4" },
             ticks: { color: "#8aa0b4" }, grid: { color: "#27384a" },
             ...(cfg.nonNegative ? { min: 0 } : {}) },
      },
      plugins: {
        legend: { labels: { color: "#e8eef4", boxWidth: 12,
                            filter: (item) => item.text !== "±band" } },
        tooltip: { filter: (item) => item.dataset.label !== "±band" },
      },
    },
  });
}

document.querySelectorAll("#ensemble-toggles button").forEach((btn) => {
  btn.addEventListener("click", () => {
    if (btn.dataset.metric === _ensembleMetric) return;
    document.querySelectorAll("#ensemble-toggles button")
      .forEach((b) => b.classList.toggle("active", b === btn));
    _ensembleMetric = btn.dataset.metric;
    renderEnsembleChart();
  });
});


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
        <td>${fmt(s.mae_precip)}</td><td>${fmt(s.precip_hit_pct, "%")}</td><td>${fmt(s.mae_wind)}</td>
        <td>${fmt(s.condition_pct, "%")}</td><td>${s.n}</td></tr>`).join("")
    : '<tr><td colspan="8" class="empty">No scored forecasts yet.</td></tr>';
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
        `${a.source}: ${fmt(a.temp_high_f, "°")}/${fmt(a.temp_low_f, "°")}, ${fmt(a.precip_mm, "mm")}, wind ${fmt(a.wind_max_mph, "mph")}, ${a.condition || "—"}`).join(" · ")
    : "<span class='empty'>No actuals recorded for this date.</span>";
  const tb = $("#daily-table tbody");
  tb.innerHTML = data.forecasts.length
    ? data.forecasts.map((f) => `<tr>
        <td>${f.service}</td><td>${fmtHorizon(f.horizon_days)}</td><td>${fmt(f.temp_high_f, "°")}</td>
        <td>${fmt(f.temp_low_f, "°")}</td><td>${fmt(f.precip_mm, "mm")}</td>
        <td>${fmt(f.wind_max_mph, "mph")}</td><td>${f.condition || "—"}</td></tr>`).join("")
    : '<tr><td colspan="7" class="empty">No forecasts for this date.</td></tr>';
}
$("#daily-load").addEventListener("click", loadDaily);
loaders.daily = () => { if (!$("#daily-date").value) $("#daily-date").value = new Date().toISOString().slice(0, 10); };


// ════════════════════════════════════════════════════════════════════════════
// RAW LOG
// ════════════════════════════════════════════════════════════════════════════
loaders.raw = async () => {
  const data = await api("/api/errors?limit=200");
  const tb = $("#raw-table tbody");
  const round2 = (v) => (v == null ? null : Math.round(v * 100) / 100);
  tb.innerHTML = data.errors.length
    ? data.errors.map((e) => `<tr>
        <td>${e.id}</td><td>${e.service}</td><td>${e.target_date}</td><td>${fmtHorizon(e.horizon_days)}</td>
        <td>${e.actuals_source}</td><td>${fmt(round2(e.temp_high_err))}</td><td>${fmt(round2(e.temp_low_err))}</td>
        <td>${fmt(round2(e.precip_err))}</td><td>${fmt(round2(e.wind_err))}</td>
        <td>${e.condition_match === null ? "—" : (e.condition_match ? "✓" : "✗")}</td></tr>`).join("")
    : '<tr><td colspan="10" class="empty">No error rows yet.</td></tr>';
};


// ── Initial load ───────────────────────────────────────────────────────────
loaders.station();
