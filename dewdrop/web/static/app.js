"use strict";

const api = (path) => fetch(path).then((r) => r.json());
const $ = (sel) => document.querySelector(sel);
const fmt = (v, suffix = "") => (v === null || v === undefined ? "—" : v + suffix);

// ── Tab switching ─────────────────────────────────────────────────────────
const loaders = {};
document.querySelectorAll("#tabs button").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll("#tabs button").forEach((b) => b.classList.remove("active"));
    document.querySelectorAll(".view").forEach((v) => v.classList.remove("active"));
    btn.classList.add("active");
    const view = btn.dataset.view;
    $("#" + view).classList.add("active");
    if (loaders[view]) loaders[view]();
  });
});

// ── Status line ─────────────────────────────────────────────────────────--
api("/health").then((h) => {
  $("#status").textContent = `${h.location} · sources: ${h.sources.join(", ")} · truth: ${h.actuals.join(", ")}`;
});

// ── Dashboard ──────────────────────────────────────────────────────────--
loaders.dashboard = async () => {
  const data = await api("/api/ensemble");
  const box = $("#ensemble-cards");
  if (!data.days.length) { box.innerHTML = '<p class="empty">No forecasts collected yet.</p>'; return; }
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

// ── Service comparison ─────────────────────────────────────────────────--
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

// ── Bias curves ────────────────────────────────────────────────────────--
let biasChart = null;
const PALETTE = ["#4fc3f7", "#ff7043", "#66bb6a", "#ab47bc", "#ffca28", "#26a69a"];
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

// ── Daily drill-down ───────────────────────────────────────────────────--
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

// ── Raw log ────────────────────────────────────────────────────────────--
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

// initial view
loaders.dashboard();
