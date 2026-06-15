/**
 * Agribuddy Card  v2.0.0
 * type: custom:agribuddy-card
 *
 * Complete rebuild for Daystrom backend. All plant data comes from flat
 * enriched fields via /api/agribuddy/plots and /api/agribuddy/plants.
 * No Verdantly/FarmOS dependencies remain.
 */

const DOMAIN = "agribuddy";
const API_BASE = "/api/agribuddy";
const CARD_VERSION = "2.0.0";

/* ─── Utilities ──────────────────────────────────────────────────────────── */

const daysAgo = n =>
  n == null ? "—" : n === 0 ? "Today" : n === 1 ? "1d ago" : `${n}d ago`;

const isoDisp = iso => {
  if (!iso) return "—";
  try { return new Date(iso + "T00:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric" }); }
  catch { return iso; }
};

const eventIcon = type => ({
  watered: "💧", fertilized: "🌿", pest_spotted: "🐛", pest: "🐛",
  harvested: "🌾", sprouted: "🌱", transplanted: "🪴", planted: "🌰",
  dead: "💀", rain_detected: "🌧️", frost_alert: "❄️", snow: "🌨️",
  needs_water: "💧", other: "📝",
})[type] || "📝";

const evColors = type => {
  if (type === "watered" || type === "rain_detected") return ["#E6F1FB", "#185FA5"];
  if (type === "fertilized") return ["#EAF3DE", "#3B6D11"];
  if (type === "frost_alert") return ["#FAECE7", "#993C1D"];
  if (type === "snow") return ["#E8F0F4", "#2E5A7A"];
  if (type === "pest_spotted" || type === "pest") return ["#FAEEDA", "#854F0B"];
  if (type === "harvested") return ["#FFF1D6", "#7A4F0A"];
  if (type === "sprouted") return ["#E6F5DA", "#2F6017"];
  if (type === "transplanted") return ["#E1F5EE", "#0F6E56"];
  if (type === "planted") return ["#E5DBC8", "#5A4221"];
  if (type === "dead") return ["#D6D6D6", "#2A2A2A"];
  if (type === "needs_water") return ["#FFF4D6", "#9C7008"];
  return ["var(--secondary-background-color)", "var(--primary-text-color)"];
};

const EVENT_LABELS = {
  watered: "Watered", fertilized: "Fertilized", pest_spotted: "Pest spotted",
  pest: "Pest spotted", harvested: "Harvested", sprouted: "Sprouted",
  transplanted: "Transplanted", planted: "Planted", dead: "Died",
  rain_detected: "Rain", frost_alert: "Frost alert", snow: "Snow",
  needs_water: "Due for water", other: "Other",
};

const PLANNER_EVENT_COLORS = {
  watered: "#5DCAA5", rain_detected: "#9FE1CB", fertilized: "#C0DD97",
  frost_alert: "#E24B4A", snow: "#A8C8DD", pest_spotted: "#D4A04A",
  pest: "#D4A04A", harvested: "#E0A547", sprouted: "#7BC453",
  transplanted: "#1D9E75", planted: "#8B6F47", dead: "#4A4A4A",
  needs_water: "#E0B23C", other: "#B0B0B0",
};

const MANUAL_EVENT_TYPES = [
  "watered", "fertilized", "pest_spotted", "harvested",
  "sprouted", "transplanted", "planted", "dead", "other",
];

const plantEmoji = type => {
  if (!type) return "🌱";
  const t = type.toLowerCase();
  if (t.includes("tomato")) return "🍅";
  if (t.includes("carrot")) return "🥕";
  if (t.includes("broccoli")) return "🥦";
  if (t.includes("lettuce")) return "🥬";
  if (t.includes("pepper")) return "🌶️";
  if (t.includes("cucumber")) return "🥒";
  if (t.includes("bean")) return "🫘";
  if (t.includes("potato")) return "🥔";
  if (t.includes("onion")) return "🧅";
  if (t.includes("garlic")) return "🧄";
  if (t.includes("corn")) return "🌽";
  if (t.includes("strawberry")) return "🍓";
  if (t.includes("squash") || t.includes("pumpkin")) return "🎃";
  if (t.includes("basil") || t.includes("herb")) return "🌿";
  if (t.includes("sunflower")) return "🌻";
  if (t.includes("rose")) return "🌹";
  if (t.includes("lavender")) return "💜";
  return "🌱";
};

const stageBadge = p => {
  if (p.is_scheduled) {
    const dpt = p.days_until_planting ?? 0;
    return [`Plants in ${dpt}d`, "#E6F1FB", "#185FA5"];
  }
  const days = p.days_growing || 0;
  const start = p.start_type === "transplant" ? "Transplant" : "Seed";
  const label = `${start} · Day ${days}`;
  return days < 7 ? [label, "#FAEEDA", "#854F0B"]
    : days < 21 ? [label, "#EAF3DE", "#3B6D11"]
      : [label, "#E1F5EE", "#0F6E56"];
};

const healthColor = p => {
  if (p.is_scheduled) return "#185FA5";
  const ds = p.days_since_watered;
  if (ds == null) return "#639922";
  const threshold = p.watering_min_days || 3;
  if (ds >= threshold + 1) return "#BA7517";
  if (ds >= threshold) return "#D4A04A";
  return "#639922";
};

const needsWater = p =>
  !p.is_scheduled
  && p.days_since_watered != null
  && p.days_since_watered >= (p.watering_min_days || 3);

const plantWaterStatus = p => {
  if (p.is_scheduled) return { badge: "", overdue: false, source: null };
  const ds = p.days_since_watered;
  const threshold = p.watering_min_days || 3;
  const overdue = (ds != null) && (ds >= threshold);
  const source = p.last_water_source || null;
  let badge = "";
  if (overdue) {
    badge = `<span class="plant-status-badge plant-status-needs" title="Needs water — ${ds}d since last watered (threshold ${threshold}d)">💧</span>`;
  } else if (source === "rain") {
    badge = `<span class="plant-status-badge plant-status-rain" title="Last watered by rain${ds != null ? ` (${ds}d ago)` : ""}">🌧</span>`;
  }
  return { badge, overdue, source };
};

const plantStatus = p => {
  const events = p.events_sorted || p.events || [];
  for (const e of events) {
    const et = (e.type || "").toLowerCase();
    if (et === "dead") return "dead";
    if (et === "harvested") return "harvested";
  }
  if (p.is_scheduled) return "scheduled";
  if (needsWater(p)) return "thirsty";
  return "healthy";
};

const statusLabel = s => ({
  healthy: "Healthy", thirsty: "Needs water", scheduled: "Scheduled",
  danger: "Frost risk", harvested: "Harvested", dead: "Dead",
})[s] || s;

const statusColor = s => ({
  healthy: "#0F6E56", thirsty: "#854F0B", scheduled: "#185FA5",
  danger: "#993C1D", harvested: "#5F5E5A", dead: "#2A2A2A",
})[s] || "#666";

/* ─── CSS ────────────────────────────────────────────────────────────────── */

const CSS = `
:host{display:block}
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
.card{background:var(--card-background-color,#fff);border-radius:var(--ha-card-border-radius,12px);border:1px solid var(--divider-color,#e0e0e0);padding:1rem 1.25rem;font-family:var(--paper-font-body1_-_font-family,sans-serif);color:var(--primary-text-color);position:relative;overflow:visible}

/* Toast notifications */
.toast-stack{position:absolute;bottom:14px;left:50%;transform:translateX(-50%);z-index:99999;display:flex;flex-direction:column-reverse;gap:7px;width:calc(100% - 28px);max-width:440px;pointer-events:none}
.toast{display:flex;align-items:flex-start;gap:10px;padding:11px 14px;border-radius:10px;font-size:13px;line-height:1.45;box-shadow:0 4px 18px rgba(0,0,0,.2);pointer-events:all;animation:toastIn .18s ease}
.toast-error{background:#7E1F1F;color:#fff}.toast-success{background:#1D9E75;color:#fff}.toast-info{background:#185FA5;color:#fff}
.toast-icon{font-size:15px;flex-shrink:0;margin-top:1px}.toast-body{flex:1}.toast-title{font-weight:600;margin-bottom:2px}.toast-msg{opacity:.88;font-size:12px}
.toast-close{background:none;border:none;color:inherit;cursor:pointer;font-size:14px;opacity:.7;padding:0;align-self:flex-start;line-height:1}
@keyframes toastIn{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}

/* Header */
.header{display:flex;align-items:center;justify-content:space-between;margin-bottom:14px;gap:8px;flex-wrap:wrap}
.hdr-left{display:flex;flex-direction:column;gap:2px;flex:1;min-width:0}
.hdr-title{font-size:15px;font-weight:600}
.hdr-sub{font-size:12px;color:var(--secondary-text-color)}
.hdr-acts{display:flex;align-items:center;gap:8px}
.gear-btn{width:32px;height:32px;border-radius:50%;border:1px solid var(--divider-color);background:var(--secondary-background-color);cursor:pointer;display:flex;align-items:center;justify-content:center;font-size:16px;color:var(--secondary-text-color)}
.gear-btn:hover{background:var(--divider-color)}

/* Buttons */
.btn{font-size:12px;padding:5px 13px;border-radius:8px;border:1px solid var(--divider-color);background:var(--secondary-background-color);cursor:pointer;color:var(--primary-text-color);font-family:inherit;transition:opacity .12s}
.btn:hover{opacity:.78}
.btn-accent{background:#1D9E75;border-color:#0F6E56;color:#fff;font-weight:500}
.btn-danger{color:#993C1D;border-color:#993C1D}
.btn-full{width:100%;padding:9px;margin-top:4px;font-size:13px}
.btn-sm{font-size:11px;padding:3px 9px}
.btn-icon{width:28px;height:28px;padding:0;display:flex;align-items:center;justify-content:center;border-radius:50%}

/* Weather metrics */
.metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-bottom:14px}
.metric{background:var(--secondary-background-color);border:1px solid var(--divider-color);border-radius:8px;padding:10px;text-align:center}
.metric-val{font-size:20px;font-weight:600}
.metric-lbl{font-size:11px;color:var(--secondary-text-color);margin-top:2px}

/* Alert banner */
.alert-banner{display:flex;align-items:center;gap:10px;padding:10px 14px;border-radius:10px;margin-bottom:14px;font-size:13px;background:linear-gradient(135deg,#FFF0E6,#FFE0CC);border:1px solid #FFD4B8;color:#7A3D10}
.alert-banner-icon{font-size:18px;flex-shrink:0}
.alert-banner-text{flex:1;line-height:1.4}
.alert-banner-close{background:none;border:none;font-size:16px;cursor:pointer;color:inherit;opacity:.6;padding:4px}
.alert-banner-close:hover{opacity:1}

/* Section headers */
.sec-title{font-size:11px;font-weight:500;letter-spacing:.06em;color:var(--secondary-text-color);text-transform:uppercase;margin-bottom:10px;display:flex;align-items:center;justify-content:space-between}
.divider{border:none;border-top:1px solid var(--divider-color);margin:12px 0}

/* Planner */
.planner-nav{display:flex;align-items:center;justify-content:space-between;margin-bottom:10px;padding:6px 10px;background:var(--secondary-background-color);border-radius:8px}
.planner-nav-btn{background:transparent;border:1px solid var(--divider-color);color:var(--primary-text-color);font-size:14px;width:28px;height:28px;border-radius:6px;cursor:pointer;font-family:inherit;display:flex;align-items:center;justify-content:center}
.planner-nav-btn:hover{background:var(--card-background-color)}
.planner-nav-label{font-size:13px;font-weight:600;flex:1;text-align:center}
.planner-nav-today{font-size:11px;padding:3px 9px;border-radius:5px;border:1px solid var(--divider-color);background:transparent;color:var(--secondary-text-color);cursor:pointer;font-family:inherit}
.planner-hdrs{display:flex;padding-left:90px;margin-bottom:4px}
.planner-hdr{flex:1;text-align:center;font-size:11px;color:var(--secondary-text-color)}
.planner-hdr.today{font-weight:600;color:var(--primary-text-color)}
.plan-row{display:flex;align-items:center;gap:6px;margin-bottom:4px}
.plan-lbl{width:84px;flex-shrink:0;font-size:12px;cursor:pointer;border-radius:4px;padding:2px 4px;transition:background .12s}
.plan-lbl:hover{background:var(--secondary-background-color)}
.plan-lbl-name{font-weight:500;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.plan-lbl-sub{font-size:10px;color:var(--secondary-text-color)}
.plan-days{flex:1;display:flex}
.plan-cell{flex:1;height:26px;display:flex;align-items:center;justify-content:center;font-size:9px}
.plan-cell.today{background:rgba(29,158,117,.08);border-radius:4px}
.plan-cell.future{opacity:.4}
.plan-legend{display:flex;gap:8px;flex-wrap:wrap;margin-top:8px}
.leg-item{display:flex;align-items:center;gap:4px;font-size:11px;color:var(--secondary-text-color)}
.evt-dot{width:9px;height:9px;border-radius:50%;display:inline-block}

/* Plants table */
.plants-scroll{max-height:320px;overflow-y:auto;background:var(--secondary-background-color);border:1px solid var(--divider-color);border-radius:10px;margin-bottom:14px;scrollbar-width:thin}
.plants-scroll::-webkit-scrollbar{width:6px}
.plants-scroll::-webkit-scrollbar-thumb{background:var(--divider-color);border-radius:3px}
.plant-table{width:100%;border-collapse:collapse;font-size:13px;table-layout:fixed}
.plant-table th{text-align:left;font-size:11px;font-weight:500;color:var(--secondary-text-color);padding:8px 10px;border-bottom:1px solid var(--divider-color);position:sticky;top:0;background:var(--secondary-background-color);z-index:1}
.plant-table td{padding:9px 10px;border-bottom:1px solid var(--divider-color);vertical-align:middle}
.plant-table tr:last-child td{border-bottom:none}
.plant-row{cursor:pointer}
.plant-row:hover td{background:rgba(29,158,117,.04)}
.plant-name-cell{display:flex;align-items:center;gap:7px;font-weight:500}
.plant-icon-wrap{position:relative;width:28px;height:28px;flex-shrink:0;display:flex;align-items:center;justify-content:center}
.plant-icon-wrap img{width:28px;height:28px;border-radius:6px;object-fit:cover}
.plant-status-badge{position:absolute;bottom:-3px;right:-5px;width:16px;height:16px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:10px;line-height:1;box-shadow:0 1px 3px rgba(0,0,0,.18);border:1.5px solid var(--card-background-color,#fff);cursor:help}
.plant-status-needs{background:#FCE2E7}
.plant-status-rain{background:#DCEEFB}
.badge{display:inline-block;font-size:11px;padding:2px 7px;border-radius:6px;font-weight:500}
.chev{color:var(--secondary-text-color);font-size:14px;text-align:right}

/* Plot strip */
.plot-strip-wrap{margin:0 -16px 8px;padding:0 16px 6px;overflow-x:auto;scrollbar-width:thin}
.plot-strip-wrap::-webkit-scrollbar{height:6px}
.plot-strip-wrap::-webkit-scrollbar-thumb{background:var(--divider-color);border-radius:3px}
.plot-strip{display:flex;gap:10px;min-width:max-content}
.plot-strip .plot-card{width:160px;flex-shrink:0}
.plot-card{background:var(--secondary-background-color);border:1px solid var(--divider-color);border-radius:10px;padding:14px;cursor:pointer;transition:border-color .12s,transform .12s}
.plot-card:hover{border-color:#1D9E75;transform:translateY(-1px)}
.plot-card-name{font-size:14px;font-weight:600;margin-bottom:4px;display:flex;align-items:center;gap:6px}
.plot-card-count{font-size:11px;color:var(--secondary-text-color)}
.plot-card-desc{font-size:11px;color:var(--secondary-text-color);margin-top:6px;line-height:1.4}
.plot-card-add{background:transparent;border:2px dashed var(--divider-color);display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;color:var(--secondary-text-color);min-height:90px}
.plot-card-add:hover{border-color:#1D9E75;color:#1D9E75}

/* Plot detail */
.plot-hdr{display:flex;align-items:center;gap:10px;margin-bottom:14px;padding-bottom:10px;border-bottom:1px solid var(--divider-color)}
.plot-back{background:none;border:none;font-size:13px;cursor:pointer;color:var(--secondary-text-color);padding:0;font-family:inherit}
.plot-back:hover{color:#1D9E75}
.plot-title{font-size:16px;font-weight:600;flex:1}

/* Overlays */
.overlay{display:none;position:fixed;inset:0;background:rgba(0,0,0,.42);z-index:9999;align-items:flex-start;justify-content:center;padding:16px;overflow-y:auto}
.overlay.open{display:flex}
.popup{background:var(--card-background-color,#fff);border:1px solid var(--divider-color);border-radius:14px;width:100%;max-width:580px;margin:auto;box-shadow:0 8px 40px rgba(0,0,0,.22);overflow:hidden}
.popup-hdr{display:flex;align-items:center;justify-content:space-between;padding:14px 16px;border-bottom:1px solid var(--divider-color);position:sticky;top:0;background:var(--card-background-color,#fff);z-index:1}
.popup-body{padding:16px;max-height:78vh;overflow-y:auto}
.popup-card{max-width:480px}

/* Plant detail card */
.tc{background:var(--card-background-color,#fff);border:0.5px solid var(--divider-color);border-radius:14px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,.06)}
.tcm-image{position:relative;height:140px;background:linear-gradient(135deg,#E8F5E9 0%,#A5D6A7 100%);display:flex;align-items:center;justify-content:center;overflow:hidden}
.tcm-image-content{font-size:80px;line-height:1;display:flex;align-items:center;justify-content:center;width:100%;height:100%}
.tcm-image-content img{width:100%;height:100%;object-fit:cover;display:block}
.tcm-status-pill{position:absolute;top:10px;right:10px;display:inline-flex;align-items:center;gap:6px;padding:4px 10px 4px 8px;border-radius:14px;background:rgba(255,255,255,.95);font-size:11px;font-weight:500;box-shadow:0 1px 3px rgba(0,0,0,.12);backdrop-filter:blur(4px)}
.tcm-status-dot{width:7px;height:7px;border-radius:50%;flex-shrink:0}
.tcm-invasive-pill{position:absolute;top:38px;right:10px;display:inline-flex;align-items:center;gap:4px;padding:3px 9px;border-radius:12px;background:rgba(252,235,235,.95);color:#791F1F;font-size:10px;font-weight:500;box-shadow:0 1px 3px rgba(0,0,0,.12)}
.tcm-body{padding:14px 16px 16px}
.tcm-name{font-size:19px;font-weight:500;color:var(--primary-text-color);line-height:1.2;margin-bottom:2px;word-wrap:break-word}
.tcm-sci{font-size:12px;font-style:italic;color:var(--secondary-text-color);margin-bottom:14px;line-height:1.3}
.tcm-tile-row{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:14px}
.tcm-tile{position:relative;overflow:hidden;border-radius:10px;padding:10px 12px;text-align:center}
.tcm-tile-light{background:#FAEEDA}
.tcm-tile-water{background:#E6F1FB}
.tcm-tile-bg{position:absolute;inset:0;display:flex;align-items:center;justify-content:flex-end;padding-right:8px;font-size:54px;line-height:1;opacity:.18;filter:saturate(0) brightness(1.1);pointer-events:none;user-select:none}
.tcm-tile-label{position:relative;z-index:1;font-size:10px;text-transform:uppercase;letter-spacing:.04em;font-weight:500}
.tcm-tile-light .tcm-tile-label{color:#854F0B}
.tcm-tile-water .tcm-tile-label{color:#0C447C}
.tcm-tile-value{position:relative;z-index:1;font-size:14px;font-weight:500;margin-top:2px;word-wrap:break-word;line-height:1.2}
.tcm-tile-light .tcm-tile-value{color:#412402}
.tcm-tile-water .tcm-tile-value{color:#042C53}
.tcm-kv-grid{display:grid;grid-template-columns:auto 1fr;gap:8px 14px;font-size:12px;line-height:1.45;margin-bottom:14px}
.tcm-kv-label{color:var(--secondary-text-color);white-space:nowrap}
.tcm-kv-value{color:var(--primary-text-color);word-wrap:break-word;text-align:right}

/* Trading card footer actions */
.tc-footer{margin-top:14px;display:flex;flex-direction:column;gap:6px}
.tc-section{border:1px solid var(--divider-color);border-radius:8px;background:var(--secondary-background-color)}
.tc-section[open]{background:var(--card-background-color,#fff)}
.tc-section-summary{font-size:13px;font-weight:500;color:var(--primary-text-color);padding:10px 12px;cursor:pointer;list-style:none;display:flex;align-items:center;gap:6px;user-select:none}
.tc-section-summary::-webkit-details-marker{display:none}
.tc-section-summary::after{content:"›";margin-left:auto;font-size:18px;color:var(--secondary-text-color);transition:transform .15s ease}
.tc-section[open] .tc-section-summary::after{transform:rotate(90deg)}
.tc-section[open] .tc-section-summary{border-bottom:1px solid var(--divider-color)}
.tc-section > div:not(.tc-section-summary){padding:10px 12px}

/* Event list */
.ev-item{display:flex;align-items:flex-start;gap:10px;padding:9px 0;border-bottom:1px solid var(--divider-color)}
.ev-item:last-child{border-bottom:none}
.ev-icon{width:32px;height:32px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:14px;flex-shrink:0}
.ev-title{font-size:13px;font-weight:500}
.ev-meta{font-size:11px;color:var(--secondary-text-color);margin-top:2px}
.ev-note{font-size:12px;color:var(--secondary-text-color);margin-top:2px;font-style:italic}
.ev-del{background:none;border:none;font-size:12px;cursor:pointer;color:var(--secondary-text-color);opacity:.5;padding:2px 4px;border-radius:4px}
.ev-del:hover{opacity:1;color:#993C1D;background:rgba(153,60,29,.08)}
.no-items{font-size:13px;color:var(--secondary-text-color);text-align:center;padding:24px 0}

/* Forms */
.form-row{display:flex;flex-direction:column;gap:5px;margin-bottom:13px}
.form-label{font-size:12px;color:var(--secondary-text-color)}
.form-input,.form-select,.form-textarea{width:100%;font-size:13px;padding:7px 10px;border-radius:8px;border:1px solid var(--divider-color);background:var(--secondary-background-color);color:var(--primary-text-color);font-family:inherit}
.form-textarea{resize:vertical;min-height:60px}
.form-input:focus,.form-select:focus,.form-textarea:focus{outline:none;border-color:#1D9E75}
.close-btn{width:28px;height:28px;border-radius:50%;border:1px solid var(--divider-color);background:var(--secondary-background-color);cursor:pointer;font-size:13px;display:flex;align-items:center;justify-content:center;color:var(--secondary-text-color);font-family:inherit}
.close-btn:hover{background:var(--divider-color)}

/* Search */
.search-row{display:flex;gap:8px;align-items:center;margin-bottom:4px}
.search-row .form-input{flex:1}
.search-results-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));gap:10px;max-height:300px;overflow-y:auto;margin-top:8px;padding:2px}
.sr-card{border:1px solid var(--divider-color);border-radius:10px;overflow:hidden;cursor:pointer;background:var(--secondary-background-color);transition:border-color .12s}
.sr-card:hover{border-color:#1D9E75}
.sr-img{width:100%;height:90px;object-fit:cover;display:block;background:var(--divider-color)}
.sr-img-ph{width:100%;height:90px;display:flex;align-items:center;justify-content:center;font-size:36px;background:var(--secondary-background-color)}
.sr-body{padding:7px 8px}
.sr-name{font-size:12px;font-weight:600;line-height:1.3;margin-bottom:2px}
.sr-sci{font-size:10px;color:var(--secondary-text-color);font-style:italic;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.sr-invasive{display:inline-block;background:#E2526A;color:#fff;font-size:10px;font-weight:700;padding:1px 5px;border-radius:3px;margin-left:4px;vertical-align:middle}
.sr-empty{font-size:13px;color:var(--secondary-text-color);text-align:center;padding:20px 0}

/* Plant info grid (add form) */
.plant-image-wrap{width:100%;height:100px;border-radius:10px;overflow:hidden;background:var(--secondary-background-color);margin-bottom:12px;display:flex;align-items:center;justify-content:center}
.plant-image-wrap img{width:100%;height:100%;object-fit:cover;display:block}
.plant-image-placeholder{width:100%;height:100px;border-radius:10px;display:flex;align-items:center;justify-content:center;font-size:52px;background:var(--secondary-background-color);margin-bottom:12px}
.plant-info-grid{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:14px}
.plant-info-cell{background:var(--secondary-background-color);border:1px solid var(--divider-color);border-radius:8px;padding:9px 11px}
.plant-info-label{font-size:10px;text-transform:uppercase;letter-spacing:.05em;color:var(--secondary-text-color);font-weight:500;margin-bottom:3px}
.plant-info-value{font-size:13px;line-height:1.4}

/* Settings */
.set-section{font-size:12px;font-weight:600;color:var(--primary-text-color);margin-bottom:12px;padding-bottom:6px;border-bottom:1px solid var(--divider-color)}
.theme-toggle{display:inline-flex;border:1px solid var(--divider-color);border-radius:8px;overflow:hidden;background:var(--secondary-background-color)}
.theme-toggle-btn{background:transparent;border:0;padding:7px 14px;font-size:12px;font-weight:500;color:var(--secondary-text-color);cursor:pointer;font-family:inherit;border-right:1px solid var(--divider-color)}
.theme-toggle-btn:last-child{border-right:0}
.theme-toggle-btn.active{background:#1D9E75;color:#fff}

/* Spinner */
.spinner{display:flex;align-items:center;justify-content:center;padding:20px;color:var(--secondary-text-color);font-size:13px;gap:8px}

/* Dark theme overrides */
:host(.dark) .card{background:#1A1A1A;border-color:#333;color:#E8E8E8}
:host(.dark) .metric{background:#252525;border-color:#333}
:host(.dark) .plants-scroll{background:#252525;border-color:#333}
:host(.dark) .plant-table th{background:#252525}
:host(.dark) .plot-card{background:#252525;border-color:#333}
:host(.dark) .form-input,:host(.dark) .form-select,:host(.dark) .form-textarea{background:#252525;border-color:#444;color:#E8E8E8}
:host(.dark) .btn{background:#252525;border-color:#444;color:#E8E8E8}
:host(.dark) .popup{background:#1A1A1A;border-color:#333}
:host(.dark) .popup-hdr{background:#1A1A1A}
:host(.dark) .tc-section{background:#252525;border-color:#333}
:host(.dark) .tc-section[open]{background:#1A1A1A}
:host(.dark) .alert-banner{background:linear-gradient(135deg,#2D1F0F,#3D2A14);border-color:#5A3D1A;color:#FFD4A0}
`;

/* ─── Card Class ─────────────────────────────────────────────────────────── */

class AgribuddyCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._plots = [];
    this._allPlants = [];
    this._view = "main";
    this._plannerOffset = 0;
    this._toasts = [];
    this._alertDismissed = false;
    this._theme = localStorage.getItem("agribuddy:theme") || "light";
    this._selectedSpecies = null;
    this._loading = true;
  }

  setConfig(config) {
    this._config = config;
  }

  set hass(hass) {
    const firstSet = !this._hass;
    this._hass = hass;
    if (firstSet) {
      this._boot();
    } else {
      this._updateLive();
    }
  }

  static getConfigElement() { return document.createElement("div"); }
  static getStubConfig() { return {}; }

  _boot() {
    this.shadowRoot.innerHTML = `<style>${CSS}</style><div class="card"><div class="spinner">Loading...</div></div>`;
    this._applyTheme();
    this._fetchData().then(() => {
      this._loading = false;
      this._renderCurrentView();
    });
  }

  _applyTheme() {
    if (this._theme === "dark") {
      this.classList.add("dark");
    } else {
      this.classList.remove("dark");
    }
  }

  /* ── Data fetching ───────────────────────────────────────────────────── */

  async _apiFetch(path, opts = {}) {
    const resp = await fetch(`${API_BASE}${path}`, {
      headers: { Authorization: `Bearer ${this._hass.auth.data.access_token}`, "Content-Type": "application/json" },
      ...opts,
    });
    const data = await resp.json();
    return { status: resp.status, data };
  }

  async _fetchData() {
    try {
      const { status, data } = await this._apiFetch("/plots");
      if (status === 200 && Array.isArray(data)) {
        this._plots = data;
        this._allPlants = data.flatMap(p => p.plants || []);
      }
    } catch (e) {
      console.error("[Agribuddy] Failed to fetch plots:", e);
    }
  }

  async _refresh() {
    await this._fetchData();
    this._renderCurrentView();
  }

  /* ── View router ─────────────────────────────────────────────────────── */

  _renderCurrentView() {
    if (!this._hass) return;
    const root = this.shadowRoot;
    root.innerHTML = `<style>${CSS}</style>`;
    const card = document.createElement("div");
    card.className = "card";
    root.appendChild(card);
    this._applyTheme();

    if (this._view === "main") {
      this._renderMain(card);
    } else if (this._view === "settings") {
      this._renderSettings(card);
    } else if (this._view.startsWith("plot:")) {
      const plotId = this._view.slice(5);
      this._renderPlotDetail(card, plotId);
    }

    // Toast stack
    const stack = document.createElement("div");
    stack.className = "toast-stack";
    card.appendChild(stack);
    this._toastStack = stack;
  }

  /* ── Main View ───────────────────────────────────────────────────────── */

  _renderMain(card) {
    const plants = this._allPlants;
    const activePlants = plants.filter(p => !["dead", "harvested"].includes(plantStatus(p)));
    const thirstyPlants = activePlants.filter(needsWater);
    const weather = this._getWeather();

    // Header
    card.innerHTML = `
      <div class="header">
        <div class="hdr-left">
          <div class="hdr-title">Agribuddy</div>
          <div class="hdr-sub">${activePlants.length} plant${activePlants.length !== 1 ? "s" : ""} growing</div>
        </div>
        <div class="hdr-acts">
          <button class="btn btn-accent" id="add-plant-btn">+ Add Plant</button>
          <button class="gear-btn" id="settings-btn" title="Settings">⚙</button>
        </div>
      </div>
    `;

    // Weather metrics
    if (weather) {
      const m = document.createElement("div");
      m.className = "metrics";
      m.innerHTML = `
        <div class="metric"><div class="metric-val">${weather.temperature ?? "—"}°</div><div class="metric-lbl">Temp</div></div>
        <div class="metric"><div class="metric-val">${weather.humidity ?? "—"}%</div><div class="metric-lbl">Humidity</div></div>
        <div class="metric"><div class="metric-val">${weather.wind_speed ?? "—"}</div><div class="metric-lbl">Wind</div></div>
        <div class="metric"><div class="metric-val">${weather.precipitation ?? "—"}</div><div class="metric-lbl">Rain</div></div>
      `;
      card.appendChild(m);
    }

    // Alert banner
    if (thirstyPlants.length > 0 && !this._alertDismissed) {
      const names = thirstyPlants.slice(0, 3).map(p => p.name || p.common_name).join(" · ");
      const more = thirstyPlants.length > 3 ? ` +${thirstyPlants.length - 3} more` : "";
      const banner = document.createElement("div");
      banner.className = "alert-banner";
      banner.innerHTML = `
        <span class="alert-banner-icon">💧</span>
        <span class="alert-banner-text"><strong>${thirstyPlants.length} plant${thirstyPlants.length > 1 ? "s" : ""} need water:</strong> ${this._esc(names)}${more}</span>
        <button class="alert-banner-close" id="dismiss-alert">✕</button>
      `;
      card.appendChild(banner);
    }

    // Week planner
    this._renderPlanner(card, activePlants);

    // Plants section
    card.appendChild(this._createSectionDivider());
    const plantsHeader = document.createElement("div");
    plantsHeader.className = "sec-title";
    plantsHeader.innerHTML = `<span>Plants (${plants.length})</span>`;
    card.appendChild(plantsHeader);

    if (plants.length === 0) {
      const empty = document.createElement("div");
      empty.className = "no-items";
      empty.textContent = "No plants yet. Add one to get started!";
      card.appendChild(empty);
    } else {
      const scroll = document.createElement("div");
      scroll.className = "plants-scroll";
      scroll.innerHTML = `
        <table class="plant-table">
          <thead><tr><th>Plant</th><th>Status</th><th>Water</th><th></th></tr></thead>
          <tbody>${plants.map(p => this._plantRow(p)).join("")}</tbody>
        </table>
      `;
      card.appendChild(scroll);
    }

    // Grow plots section
    card.appendChild(this._createSectionDivider());
    const plotsHeader = document.createElement("div");
    plotsHeader.className = "sec-title";
    plotsHeader.innerHTML = `<span>Grow Plots</span>`;
    card.appendChild(plotsHeader);
    this._renderPlotStrip(card);

    // Event bindings
    this._bindMainEvents(card);
  }

  _plantRow(p) {
    const name = p.name || p.common_name || "Unnamed";
    const emoji = plantEmoji(name);
    const img = p.image_url
      ? `<img src="${this._esc(p.image_url)}" loading="lazy" onerror="this.outerHTML='<span style=&quot;font-size:20px&quot;>${emoji}</span>'">`
      : `<span style="font-size:20px">${emoji}</span>`;
    const ws = plantWaterStatus(p);
    const [badgeText, badgeBg, badgeColor] = stageBadge(p);
    const waterText = p.is_scheduled ? "—" : daysAgo(p.days_since_watered);

    return `<tr class="plant-row" data-id="${p.id}">
      <td><div class="plant-name-cell"><div class="plant-icon-wrap">${img}${ws.badge}</div>${this._esc(name)}</div></td>
      <td><span class="badge" style="background:${badgeBg};color:${badgeColor}">${badgeText}</span></td>
      <td style="font-size:12px;color:var(--secondary-text-color)">${waterText}</td>
      <td class="chev">›</td>
    </tr>`;
  }

  _renderPlanner(card, plants) {
    if (plants.length === 0) return;

    const sec = document.createElement("div");
    sec.className = "sec-title";
    sec.textContent = "This Week";
    card.appendChild(sec);

    const today = new Date();
    today.setHours(0, 0, 0, 0);
    const startOfWeek = new Date(today);
    startOfWeek.setDate(today.getDate() - today.getDay() + (this._plannerOffset * 7));
    const days = Array.from({ length: 7 }, (_, i) => {
      const d = new Date(startOfWeek);
      d.setDate(startOfWeek.getDate() + i);
      return d;
    });

    // Nav
    const nav = document.createElement("div");
    nav.className = "planner-nav";
    nav.innerHTML = `
      <button class="planner-nav-btn" id="plan-prev">‹</button>
      <span class="planner-nav-label">${startOfWeek.toLocaleDateString("en-US", { month: "short", day: "numeric" })} – ${days[6].toLocaleDateString("en-US", { month: "short", day: "numeric" })}</span>
      ${this._plannerOffset !== 0 ? `<button class="planner-nav-today" id="plan-today">Today</button>` : ""}
      <button class="planner-nav-btn" id="plan-next">›</button>
    `;
    card.appendChild(nav);

    // Day headers
    const hdrs = document.createElement("div");
    hdrs.className = "planner-hdrs";
    hdrs.innerHTML = days.map(d => {
      const isToday = d.toDateString() === today.toDateString();
      return `<div class="planner-hdr${isToday ? " today" : ""}">${d.toLocaleDateString("en-US", { weekday: "short" }).slice(0, 2)}</div>`;
    }).join("");
    card.appendChild(hdrs);

    // Plant rows (max 8 visible)
    const visiblePlants = plants.slice(0, 8);
    visiblePlants.forEach(p => {
      const events = p.events_sorted || p.events || [];
      const row = document.createElement("div");
      row.className = "plan-row";
      const cellsHtml = days.map(d => {
        const iso = d.toISOString().slice(0, 10);
        const isToday = d.toDateString() === today.toDateString();
        const isFuture = d > today;
        const dayEvents = events.filter(e => (e.date || "").slice(0, 10) === iso);
        const dots = dayEvents.map(e => {
          const color = PLANNER_EVENT_COLORS[(e.type || "").toLowerCase()] || PLANNER_EVENT_COLORS.other;
          return `<span class="evt-dot" style="background:${color};width:6px;height:6px" title="${EVENT_LABELS[(e.type || "").toLowerCase()] || e.type}"></span>`;
        }).join("");
        return `<div class="plan-cell${isToday ? " today" : ""}${isFuture ? " future" : ""}">${dots}</div>`;
      }).join("");

      row.innerHTML = `
        <div class="plan-lbl" data-id="${p.id}">
          <div class="plan-lbl-name">${this._esc((p.name || "").slice(0, 12))}</div>
          <div class="plan-lbl-sub">${daysAgo(p.days_since_watered)}</div>
        </div>
        <div class="plan-days">${cellsHtml}</div>
      `;
      card.appendChild(row);
    });

    // Legend
    const seen = new Set();
    visiblePlants.forEach(p => {
      (p.events_sorted || p.events || []).forEach(e => {
        const t = (e.type || "").toLowerCase();
        if (PLANNER_EVENT_COLORS[t]) seen.add(t);
      });
    });
    if (seen.size > 0) {
      const legend = document.createElement("div");
      legend.className = "plan-legend";
      legend.innerHTML = [...seen].map(t =>
        `<span class="leg-item"><span class="evt-dot" style="background:${PLANNER_EVENT_COLORS[t]}"></span>${EVENT_LABELS[t] || t}</span>`
      ).join("");
      card.appendChild(legend);
    }
  }

  _renderPlotStrip(card) {
    const wrap = document.createElement("div");
    wrap.className = "plot-strip-wrap";
    const strip = document.createElement("div");
    strip.className = "plot-strip";

    this._plots.forEach(plot => {
      const tile = document.createElement("div");
      tile.className = "plot-card";
      tile.dataset.id = plot.id;
      const count = plot.plant_count || (plot.plants || []).length;
      tile.innerHTML = `
        <div class="plot-card-name">${plot.virtual ? "📦" : "🌱"} ${this._esc(plot.name)}</div>
        <div class="plot-card-count">${count} plant${count !== 1 ? "s" : ""}</div>
        ${plot.description && !plot.virtual ? `<div class="plot-card-desc">${this._esc(plot.description.slice(0, 60))}</div>` : ""}
      `;
      strip.appendChild(tile);
    });

    // Add plot tile
    const addTile = document.createElement("div");
    addTile.className = "plot-card plot-card-add";
    addTile.id = "add-plot-tile";
    addTile.innerHTML = `<span style="font-size:20px">+</span><span style="font-size:11px;margin-top:4px">New Plot</span>`;
    strip.appendChild(addTile);

    wrap.appendChild(strip);
    card.appendChild(wrap);
  }

  _bindMainEvents(card) {
    card.querySelector("#add-plant-btn")?.addEventListener("click", () => this._openAddPlant());
    card.querySelector("#settings-btn")?.addEventListener("click", () => { this._view = "settings"; this._renderCurrentView(); });
    card.querySelector("#dismiss-alert")?.addEventListener("click", () => { this._alertDismissed = true; this._renderCurrentView(); });
    card.querySelector("#plan-prev")?.addEventListener("click", () => { this._plannerOffset--; this._renderCurrentView(); });
    card.querySelector("#plan-next")?.addEventListener("click", () => { this._plannerOffset++; this._renderCurrentView(); });
    card.querySelector("#plan-today")?.addEventListener("click", () => { this._plannerOffset = 0; this._renderCurrentView(); });
    card.querySelector("#add-plot-tile")?.addEventListener("click", () => this._openCreatePlot());

    // Plant rows
    card.querySelectorAll(".plant-row").forEach(row => {
      row.addEventListener("click", () => this._openPlantDetail(row.dataset.id));
    });

    // Planner labels
    card.querySelectorAll(".plan-lbl[data-id]").forEach(lbl => {
      lbl.addEventListener("click", (e) => { e.stopPropagation(); this._openPlantDetail(lbl.dataset.id); });
    });

    // Plot cards
    card.querySelectorAll(".plot-card[data-id]").forEach(tile => {
      tile.addEventListener("click", () => { this._view = `plot:${tile.dataset.id}`; this._renderCurrentView(); });
    });
  }

  /* ── Plot Detail View ────────────────────────────────────────────────── */

  _renderPlotDetail(card, plotId) {
    const plot = this._plots.find(p => p.id === plotId);
    if (!plot) { this._view = "main"; this._renderCurrentView(); return; }

    const plants = plot.plants || [];
    card.innerHTML = `
      <div class="plot-hdr">
        <button class="plot-back" id="plot-back">← Back</button>
        <div class="plot-title">${this._esc(plot.name)}</div>
        ${!plot.virtual ? `<button class="btn btn-sm btn-danger" id="delete-plot-btn">Delete</button>` : ""}
      </div>
      ${plot.description ? `<p style="font-size:13px;color:var(--secondary-text-color);margin-bottom:14px">${this._esc(plot.description)}</p>` : ""}
      <div class="sec-title"><span>Plants (${plants.length})</span><button class="btn btn-sm btn-accent" id="add-to-plot-btn">+ Add</button></div>
    `;

    if (plants.length === 0) {
      const empty = document.createElement("div");
      empty.className = "no-items";
      empty.textContent = "No plants in this plot yet.";
      card.appendChild(empty);
    } else {
      const scroll = document.createElement("div");
      scroll.className = "plants-scroll";
      scroll.innerHTML = `
        <table class="plant-table">
          <thead><tr><th>Plant</th><th>Status</th><th>Water</th><th></th></tr></thead>
          <tbody>${plants.map(p => this._plantRow(p)).join("")}</tbody>
        </table>
      `;
      card.appendChild(scroll);
    }

    // Bindings
    card.querySelector("#plot-back").addEventListener("click", () => { this._view = "main"; this._renderCurrentView(); });
    card.querySelector("#add-to-plot-btn")?.addEventListener("click", () => this._openAddPlant(plotId));
    card.querySelector("#delete-plot-btn")?.addEventListener("click", () => this._deletePlot(plotId));
    card.querySelectorAll(".plant-row").forEach(row => {
      row.addEventListener("click", () => this._openPlantDetail(row.dataset.id));
    });
  }

  async _deletePlot(plotId) {
    if (!confirm("Delete this plot? Plants will be moved to Unassigned.")) return;
    try {
      await this._apiFetch(`/plots/${plotId}`, { method: "DELETE" });
      this._ok("Plot deleted");
      this._view = "main";
      await this._refresh();
    } catch (e) {
      this._err("Failed to delete plot", String(e));
    }
  }

  /* ── Settings View ───────────────────────────────────────────────────── */

  _renderSettings(card) {
    card.innerHTML = `
      <div class="plot-hdr">
        <button class="plot-back" id="settings-back">← Back</button>
        <div class="plot-title">Settings</div>
      </div>
      <div class="set-section">Card Display</div>
      <div class="form-row">
        <div class="form-label">Theme</div>
        <div class="theme-toggle">
          <button class="theme-toggle-btn${this._theme === "light" ? " active" : ""}" data-theme="light">☀ Light</button>
          <button class="theme-toggle-btn${this._theme === "dark" ? " active" : ""}" data-theme="dark">🌙 Dark</button>
        </div>
      </div>
      <hr class="divider">
      <div class="set-section">Connection</div>
      <div id="conn-status" class="spinner">Checking...</div>
      <hr class="divider">
      <div style="font-size:11px;color:var(--secondary-text-color);text-align:center">Agribuddy Card v${CARD_VERSION}</div>
    `;

    card.querySelector("#settings-back").addEventListener("click", () => { this._view = "main"; this._renderCurrentView(); });
    card.querySelectorAll(".theme-toggle-btn").forEach(btn => {
      btn.addEventListener("click", () => {
        this._theme = btn.dataset.theme;
        localStorage.setItem("agribuddy:theme", this._theme);
        this._applyTheme();
        this._renderCurrentView();
      });
    });

    this._apiFetch("/test_connection").then(({ data }) => {
      const el = card.querySelector("#conn-status");
      if (el) el.innerHTML = data.ok
        ? `<span style="color:#0F6E56">✓ ${this._esc(data.message)}</span>`
        : `<span style="color:#993C1D">✗ ${this._esc(data.message || "Connection failed")}</span>`;
    });
  }

  /* ── Plant Detail Overlay ────────────────────────────────────────────── */

  _openPlantDetail(plantId) {
    const plant = this._allPlants.find(p => p.id === plantId);
    if (!plant) return;

    const status = plantStatus(plant);
    const sColor = statusColor(status);
    const sLabel = statusLabel(status);
    const name = plant.name || plant.common_name || "Unnamed";
    const sci = plant.scientific_name || "";
    const emoji = plantEmoji(name);
    const imgHtml = plant.image_url
      ? `<img src="${this._esc(plant.image_url)}" onerror="this.outerHTML='<span style=&quot;font-size:80px&quot;>${emoji}</span>'">`
      : `<span style="font-size:80px">${emoji}</span>`;

    const events = plant.events_sorted || plant.events || [];
    const plots = this._plots.filter(p => !p.virtual);

    const overlay = document.createElement("div");
    overlay.className = "overlay open";
    overlay.innerHTML = `
      <div class="popup popup-card">
        <div class="tc">
          <div class="tcm-image">
            <div class="tcm-image-content">${imgHtml}</div>
            <div class="tcm-status-pill" style="color:${sColor}">
              <span class="tcm-status-dot" style="background:${sColor}"></span>${sLabel}
            </div>
            ${plant.invasive_alert ? `<div class="tcm-invasive-pill">⚠ Invasive</div>` : ""}
          </div>
          <div class="tcm-body">
            <div class="tcm-name">${this._esc(name)}</div>
            <div class="tcm-sci">${this._esc(sci)}</div>

            <div class="tcm-tile-row">
              <div class="tcm-tile tcm-tile-light">
                <div class="tcm-tile-bg">☀</div>
                <div class="tcm-tile-label">Light</div>
                <div class="tcm-tile-value">${this._esc(plant.light_requirements || "—")}</div>
              </div>
              <div class="tcm-tile tcm-tile-water">
                <div class="tcm-tile-bg">💧</div>
                <div class="tcm-tile-label">Water</div>
                <div class="tcm-tile-value">${this._esc(plant.water_use || "—")}</div>
              </div>
            </div>

            <div class="tcm-kv-grid">
              ${this._kvRow("Watering", plant.watering_min_days && plant.watering_max_days ? `Every ${plant.watering_min_days}–${plant.watering_max_days} days` : "—")}
              ${this._kvRow("Last watered", plant.last_watered ? `${isoDisp(plant.last_watered)} (${plant.last_water_source || "manual"})` : "Never")}
              ${this._kvRow("Days growing", plant.days_growing != null ? `${plant.days_growing}` : "—")}
              ${this._kvRow("Start type", plant.start_type || "—")}
              ${this._kvRow("Start date", isoDisp(plant.start_date))}
              ${this._kvRow("Hardiness", plant.hardiness_zone_range || "—")}
              ${this._kvRow("Soil", plant.soil_preference || "—")}
              ${this._kvRow("Harvest", plant.harvest_range || "—")}
              ${plant.toxicity_display && plant.toxicity_display !== "Non-toxic" ? this._kvRow("Toxicity", plant.toxicity_display) : ""}
            </div>

            <div class="tc-footer">
              <!-- Log event -->
              <details class="tc-section">
                <summary class="tc-section-summary">📝 Log Event</summary>
                <div>
                  <div class="form-row">
                    <select class="form-select" id="evt-type">
                      ${MANUAL_EVENT_TYPES.map(t => `<option value="${t}">${EVENT_LABELS[t] || t}</option>`).join("")}
                    </select>
                  </div>
                  <div class="form-row">
                    <input type="text" class="form-input" id="evt-note" placeholder="Note (optional)">
                  </div>
                  <div class="form-row">
                    <input type="date" class="form-input" id="evt-date" value="${new Date().toISOString().slice(0, 10)}">
                  </div>
                  <button class="btn btn-accent btn-full" id="log-evt-btn">Log Event</button>
                </div>
              </details>

              <!-- Event history -->
              <details class="tc-section">
                <summary class="tc-section-summary">📅 History (${events.length})</summary>
                <div>
                  ${events.length === 0 ? `<div class="no-items">No events yet</div>` :
                    events.slice(0, 50).map(e => {
                      const [bg, fg] = evColors((e.type || "").toLowerCase());
                      return `<div class="ev-item">
                        <div class="ev-icon" style="background:${bg};color:${fg}">${eventIcon((e.type || "").toLowerCase())}</div>
                        <div style="flex:1;min-width:0">
                          <div class="ev-title">${EVENT_LABELS[(e.type || "").toLowerCase()] || e.type || "Event"}</div>
                          <div class="ev-meta">${isoDisp(e.date)}</div>
                          ${e.note ? `<div class="ev-note">${this._esc(e.note)}</div>` : ""}
                        </div>
                        <button class="ev-del" data-eid="${e.id}" title="Delete event">✕</button>
                      </div>`;
                    }).join("")}
                </div>
              </details>

              <!-- Edit plant -->
              <details class="tc-section">
                <summary class="tc-section-summary">✏️ Edit</summary>
                <div>
                  <div class="form-row">
                    <label class="form-label">Name</label>
                    <input type="text" class="form-input" id="edit-name" value="${this._esc(plant.name || "")}">
                  </div>
                  <div class="form-row">
                    <label class="form-label">Start type</label>
                    <select class="form-select" id="edit-start-type">
                      <option value="seed"${plant.start_type === "seed" ? " selected" : ""}>Seed</option>
                      <option value="transplant"${plant.start_type === "transplant" ? " selected" : ""}>Transplant</option>
                      <option value="cutting"${plant.start_type === "cutting" ? " selected" : ""}>Cutting</option>
                      <option value="division"${plant.start_type === "division" ? " selected" : ""}>Division</option>
                    </select>
                  </div>
                  <div class="form-row">
                    <label class="form-label">Start date</label>
                    <input type="date" class="form-input" id="edit-start-date" value="${plant.start_date || ""}">
                  </div>
                  <div class="form-row">
                    <label class="form-label">Grow plot</label>
                    <select class="form-select" id="edit-plot">
                      <option value="">Unassigned</option>
                      ${plots.map(pl => `<option value="${pl.id}"${pl.id === plant.plot_id ? " selected" : ""}>${this._esc(pl.name)}</option>`).join("")}
                    </select>
                  </div>
                  <button class="btn btn-accent btn-full" id="save-edit-btn">Save Changes</button>
                </div>
              </details>

              <!-- Overrides -->
              <details class="tc-section">
                <summary class="tc-section-summary">🔧 Watering Override</summary>
                <div>
                  <div class="form-row">
                    <label class="form-label">Min days between watering</label>
                    <input type="number" class="form-input" id="ov-min" min="1" max="60" value="${plant.watering_min_days || ""}">
                  </div>
                  <div class="form-row">
                    <label class="form-label">Max days between watering</label>
                    <input type="number" class="form-input" id="ov-max" min="1" max="60" value="${plant.watering_max_days || ""}">
                  </div>
                  <button class="btn btn-accent btn-full" id="save-ov-btn">Save Override</button>
                </div>
              </details>

              <!-- Remove -->
              <button class="btn btn-danger btn-full" id="remove-plant-btn" style="margin-top:8px">Remove Plant</button>
            </div>
          </div>
        </div>
      </div>
    `;

    this.shadowRoot.appendChild(overlay);
    overlay.addEventListener("click", (e) => { if (e.target === overlay) overlay.remove(); });

    // Log event
    overlay.querySelector("#log-evt-btn")?.addEventListener("click", async () => {
      const type = overlay.querySelector("#evt-type").value;
      const note = overlay.querySelector("#evt-note").value.trim();
      const date = overlay.querySelector("#evt-date").value;
      try {
        await this._hass.callService(DOMAIN, "log_event", {
          plant_id: plant.id,
          event_type: type,
          event_note: note,
          ...(date ? { event_date: date } : {}),
        });
        overlay.remove();
        this._ok(`${EVENT_LABELS[type] || type} logged`);
        setTimeout(() => this._refresh(), 500);
      } catch (e) { this._err("Failed to log event", this._fmtErr(e)); }
    });

    // Delete events
    overlay.querySelectorAll(".ev-del").forEach(btn => {
      btn.addEventListener("click", async (e) => {
        e.stopPropagation();
        const eid = btn.dataset.eid;
        if (!eid || !confirm("Delete this event?")) return;
        try {
          await this._hass.callService(DOMAIN, "remove_event", { plant_id: plant.id, event_id: eid });
          this._ok("Event removed");
          overlay.remove();
          setTimeout(() => this._refresh(), 500);
        } catch (e) { this._err("Failed to remove event", this._fmtErr(e)); }
      });
    });

    // Save edit
    overlay.querySelector("#save-edit-btn")?.addEventListener("click", async () => {
      const newName = overlay.querySelector("#edit-name").value.trim();
      const newType = overlay.querySelector("#edit-start-type").value;
      const newDate = overlay.querySelector("#edit-start-date").value;
      const newPlot = overlay.querySelector("#edit-plot").value;
      try {
        await this._hass.callService(DOMAIN, "update_plant", {
          plant_id: plant.id,
          ...(newName ? { plant_name: newName } : {}),
          start_type: newType,
          ...(newDate ? { start_date: newDate } : {}),
          plot_id: newPlot,
        });
        overlay.remove();
        this._ok("Plant updated");
        setTimeout(() => this._refresh(), 500);
      } catch (e) { this._err("Failed to update", this._fmtErr(e)); }
    });

    // Save override
    overlay.querySelector("#save-ov-btn")?.addEventListener("click", async () => {
      const minVal = overlay.querySelector("#ov-min").value;
      const maxVal = overlay.querySelector("#ov-max").value;
      const overrides = {};
      if (minVal) overrides.watering_min_days = parseInt(minVal, 10);
      if (maxVal) overrides.watering_max_days = parseInt(maxVal, 10);
      try {
        await this._hass.callService(DOMAIN, "update_plant_overrides", {
          plant_id: plant.id,
          overrides,
        });
        overlay.remove();
        this._ok("Override saved");
        setTimeout(() => this._refresh(), 500);
      } catch (e) { this._err("Failed to save override", this._fmtErr(e)); }
    });

    // Remove plant
    overlay.querySelector("#remove-plant-btn")?.addEventListener("click", async () => {
      if (!confirm(`Remove "${name}" permanently?`)) return;
      try {
        await this._hass.callService(DOMAIN, "remove_plant", { plant_id: plant.id });
        overlay.remove();
        this._ok(`${name} removed`);
        setTimeout(() => this._refresh(), 500);
      } catch (e) { this._err("Failed to remove plant", this._fmtErr(e)); }
    });
  }

  _kvRow(label, value) {
    return `<div class="tcm-kv-label">${label}</div><div class="tcm-kv-value">${this._esc(String(value || "—"))}</div>`;
  }

  /* ── Add Plant Flow ──────────────────────────────────────────────────── */

  _openAddPlant(plotId = "") {
    this._selectedSpecies = null;
    const overlay = document.createElement("div");
    overlay.className = "overlay open";
    overlay.innerHTML = `
      <div class="popup">
        <div class="popup-hdr">
          <span style="font-weight:600">Add Plant</span>
          <button class="close-btn" id="close-add">✕</button>
        </div>
        <div class="popup-body">
          <!-- Step 1: Search -->
          <div id="step-search">
            <div class="form-row">
              <label class="form-label">Search for a plant species</label>
              <div class="search-row">
                <input type="text" class="form-input" id="search-input" placeholder="e.g. Cherry Tomato, Basil...">
                <button class="btn btn-accent" id="search-btn">Search</button>
              </div>
            </div>
            <div id="search-spinner" style="display:none" class="spinner">Searching...</div>
            <div id="search-results" style="display:none">
              <div style="font-size:11px;color:var(--secondary-text-color);margin-bottom:6px" id="result-count"></div>
              <div class="search-results-grid" id="results-grid"></div>
            </div>
          </div>

          <!-- Step 2: Confirm -->
          <div id="step-form" style="display:none">
            <button class="btn btn-sm" id="back-to-search" style="margin-bottom:12px">← Back to search</button>
            <div id="add-plant-image"></div>
            <div style="font-size:16px;font-weight:600;margin-bottom:2px" id="add-common-name"></div>
            <div style="font-size:12px;font-style:italic;color:var(--secondary-text-color);margin-bottom:12px" id="add-sci-name"></div>
            <div class="plant-info-grid" id="add-info-grid"></div>
            <hr class="divider">
            <div class="form-row">
              <label class="form-label">Display name</label>
              <input type="text" class="form-input" id="add-name">
            </div>
            <div class="form-row">
              <label class="form-label">Start type</label>
              <select class="form-select" id="add-start-type">
                <option value="seed">Seed</option>
                <option value="transplant">Transplant</option>
                <option value="cutting">Cutting</option>
                <option value="division">Division</option>
              </select>
            </div>
            <div class="form-row">
              <label class="form-label">Start date</label>
              <input type="date" class="form-input" id="add-start-date" value="${new Date().toISOString().slice(0, 10)}">
            </div>
            <div class="form-row">
              <label class="form-label">Grow plot</label>
              <select class="form-select" id="add-plot">
                <option value="">Unassigned</option>
                ${this._plots.filter(p => !p.virtual).map(p => `<option value="${p.id}"${p.id === plotId ? " selected" : ""}>${this._esc(p.name)}</option>`).join("")}
              </select>
            </div>
            <button class="btn btn-accent btn-full" id="confirm-add-btn">Add Plant</button>
          </div>
        </div>
      </div>
    `;

    this.shadowRoot.appendChild(overlay);
    overlay.addEventListener("click", (e) => { if (e.target === overlay) overlay.remove(); });
    overlay.querySelector("#close-add").addEventListener("click", () => overlay.remove());
    overlay.querySelector("#back-to-search")?.addEventListener("click", () => {
      overlay.querySelector("#step-search").style.display = "block";
      overlay.querySelector("#step-form").style.display = "none";
    });

    const searchInput = overlay.querySelector("#search-input");
    const doSearch = async () => {
      const q = searchInput.value.trim();
      if (!q) return;
      overlay.querySelector("#search-spinner").style.display = "block";
      overlay.querySelector("#search-results").style.display = "none";
      try {
        const { status, data } = await this._apiFetch(`/search_plants?q=${encodeURIComponent(q)}`);
        overlay.querySelector("#search-spinner").style.display = "none";
        if (status !== 200) { this._err("Search failed", data.message || `HTTP ${status}`); return; }
        const results = Array.isArray(data?.results) ? data.results : Array.isArray(data) ? data : [];
        if (!results.length) {
          overlay.querySelector("#results-grid").innerHTML = `<div class="sr-empty">No results for "${this._esc(q)}"</div>`;
          overlay.querySelector("#search-results").style.display = "block";
          return;
        }
        overlay.querySelector("#result-count").textContent = `${results.length} result${results.length !== 1 ? "s" : ""}`;
        overlay.querySelector("#results-grid").innerHTML = results.slice(0, 20).map((r, i) => {
          const cname = r.common_name || r.variety_name || r.scientific_name || "Unknown";
          const img = r.image_url || "";
          const thumb = img
            ? `<img class="sr-img" src="${this._esc(img)}" loading="lazy" onerror="this.outerHTML='<div class=\\'sr-img-ph\\'>${plantEmoji(cname)}</div>'">`
            : `<div class="sr-img-ph">${plantEmoji(cname)}</div>`;
          const invasive = r.invasive_alert ? `<span class="sr-invasive">⚠</span>` : "";
          return `<div class="sr-card" data-i="${i}">${thumb}<div class="sr-body"><div class="sr-name">${this._esc(cname)} ${invasive}</div><div class="sr-sci">${this._esc(r.scientific_name || "")}</div></div></div>`;
        }).join("");
        overlay.querySelector("#search-results").style.display = "block";

        overlay.querySelectorAll(".sr-card").forEach(card => {
          card.addEventListener("click", () => {
            this._selectSearchResult(results[parseInt(card.dataset.i, 10)], overlay);
          });
        });
      } catch (e) {
        overlay.querySelector("#search-spinner").style.display = "none";
        this._err("Search failed", this._fmtErr(e));
      }
    };

    overlay.querySelector("#search-btn").addEventListener("click", doSearch);
    searchInput.addEventListener("keydown", e => { if (e.key === "Enter") { e.preventDefault(); doSearch(); } });

    // Confirm add
    overlay.querySelector("#confirm-add-btn").addEventListener("click", async () => {
      const name = overlay.querySelector("#add-name").value.trim();
      const sel = this._selectedSpecies || {};
      const speciesId = sel.species_id || sel.variety_id || sel.id || sel.scientific_name || "";
      const startType = overlay.querySelector("#add-start-type").value;
      const startDate = overlay.querySelector("#add-start-date").value;
      const selectedPlot = overlay.querySelector("#add-plot").value;

      if (!name) { this._err("Name required", "Enter a display name."); return; }
      if (!speciesId) { this._err("No plant selected", "Search and select a plant first."); return; }

      try {
        await this._hass.callService(DOMAIN, "add_plant", {
          plant_name: name,
          species_id: String(speciesId),
          start_type: startType,
          start_date: startDate,
          plot_id: selectedPlot,
          species_data: sel,
        });
        overlay.remove();
        this._ok(`${name} added!`);
        setTimeout(() => this._refresh(), 500);
      } catch (e) { this._err("Failed to add plant", this._fmtErr(e)); }
    });

    searchInput.focus();
  }

  _selectSearchResult(result, overlay) {
    this._selectedSpecies = result;
    overlay.querySelector("#step-search").style.display = "none";
    overlay.querySelector("#step-form").style.display = "block";

    const commonName = result.common_name || result.variety_name || result.scientific_name || "Unknown";
    const sci = result.scientific_name || "";
    const emoji = plantEmoji(commonName);

    // Image
    const imgWrap = overlay.querySelector("#add-plant-image");
    if (result.image_url) {
      imgWrap.innerHTML = `<div class="plant-image-wrap"><img src="${this._esc(result.image_url)}" loading="lazy" onerror="this.parentElement.innerHTML='<div class=&quot;plant-image-placeholder&quot;>${emoji}</div>'"></div>`;
    } else {
      imgWrap.innerHTML = `<div class="plant-image-placeholder">${emoji}</div>`;
    }

    overlay.querySelector("#add-common-name").textContent = commonName;
    overlay.querySelector("#add-sci-name").textContent = sci;
    overlay.querySelector("#add-name").value = commonName;

    // Info grid from flat fields
    const cells = [];
    if (result.light_requirements) cells.push({ label: "☀️ Light", value: result.light_requirements });
    if (result.water_use || result.water_requirement) cells.push({ label: "💧 Water", value: result.water_use || result.water_requirement });
    if (result.hardiness_zone_range) cells.push({ label: "🗺 Hardiness", value: result.hardiness_zone_range });
    if (result.soil_preference) cells.push({ label: "🌱 Soil", value: result.soil_preference });
    if (result.harvest_range) cells.push({ label: "🌾 Harvest", value: result.harvest_range });
    if (result.soil_ph_range) cells.push({ label: "⚗ pH", value: result.soil_ph_range });
    if (result.growing_season) cells.push({ label: "📅 Season", value: result.growing_season });
    if (result.plant_spacing || result.spacing_requirement) cells.push({ label: "↔ Spacing", value: result.plant_spacing || result.spacing_requirement });

    const grid = overlay.querySelector("#add-info-grid");
    if (cells.length === 0) {
      grid.innerHTML = `<div style="grid-column:1/-1;font-size:12px;color:var(--secondary-text-color)">No detailed growing info available for this variety.</div>`;
    } else {
      grid.innerHTML = cells.map(c => `
        <div class="plant-info-cell">
          <div class="plant-info-label">${c.label}</div>
          <div class="plant-info-value">${this._esc(String(c.value))}</div>
        </div>`).join("");
    }
  }

  /* ── Create Plot ─────────────────────────────────────────────────────── */

  _openCreatePlot() {
    const overlay = document.createElement("div");
    overlay.className = "overlay open";
    overlay.innerHTML = `
      <div class="popup" style="max-width:400px">
        <div class="popup-hdr">
          <span style="font-weight:600">New Grow Plot</span>
          <button class="close-btn" id="close-plot">✕</button>
        </div>
        <div class="popup-body">
          <div class="form-row">
            <label class="form-label">Name</label>
            <input type="text" class="form-input" id="plot-name" placeholder="e.g. Raised Bed, Herb Pots...">
          </div>
          <div class="form-row">
            <label class="form-label">Description (optional)</label>
            <textarea class="form-textarea" id="plot-desc" placeholder="What's in this plot?"></textarea>
          </div>
          <button class="btn btn-accent btn-full" id="create-plot-btn">Create Plot</button>
        </div>
      </div>
    `;

    this.shadowRoot.appendChild(overlay);
    overlay.addEventListener("click", (e) => { if (e.target === overlay) overlay.remove(); });
    overlay.querySelector("#close-plot").addEventListener("click", () => overlay.remove());

    overlay.querySelector("#create-plot-btn").addEventListener("click", async () => {
      const name = overlay.querySelector("#plot-name").value.trim();
      const desc = overlay.querySelector("#plot-desc").value.trim();
      if (!name) { this._err("Name required"); return; }
      try {
        await this._apiFetch("/plot_create", {
          method: "POST",
          body: JSON.stringify({ name, description: desc }),
        });
        overlay.remove();
        this._ok(`"${name}" created`);
        setTimeout(() => this._refresh(), 500);
      } catch (e) { this._err("Failed to create plot", this._fmtErr(e)); }
    });

    overlay.querySelector("#plot-name").focus();
  }

  /* ── Weather ─────────────────────────────────────────────────────────── */

  _getWeather() {
    if (!this._hass) return null;
    const weatherId = this._config?.weather_entity || "";
    const sensors = {};
    for (const [id, state] of Object.entries(this._hass.states)) {
      if (id.startsWith("sensor.agribuddy_")) {
        const attr = state.attributes || {};
        if (id.includes("temperature")) sensors.temperature = state.state;
        else if (id.includes("humidity")) sensors.humidity = state.state;
        else if (id.includes("wind")) sensors.wind_speed = state.state;
        else if (id.includes("precipitation")) sensors.precipitation = state.state;
      }
    }
    if (Object.keys(sensors).length > 0) return sensors;
    if (weatherId && this._hass.states[weatherId]) {
      const w = this._hass.states[weatherId].attributes;
      return {
        temperature: w.temperature,
        humidity: w.humidity,
        wind_speed: w.wind_speed,
        precipitation: w.precipitation || 0,
      };
    }
    return null;
  }

  /* ── Helpers ─────────────────────────────────────────────────────────── */

  _createSectionDivider() {
    const hr = document.createElement("hr");
    hr.className = "divider";
    return hr;
  }

  _esc(s) {
    if (!s) return "";
    const d = document.createElement("div");
    d.textContent = String(s);
    return d.innerHTML;
  }

  _fmtErr(e) {
    if (!e) return "Unknown error";
    if (typeof e === "string") return e;
    if (e.message) return e.message;
    return String(e);
  }

  /* ── Toast notifications ─────────────────────────────────────────────── */

  _toast(type, title, msg = "") {
    const icons = { error: "⚠", success: "✓", info: "ℹ" };
    const stack = this._toastStack || this.shadowRoot.querySelector(".toast-stack");
    if (!stack) return;
    const el = document.createElement("div");
    el.className = `toast toast-${type}`;
    el.innerHTML = `
      <span class="toast-icon">${icons[type] || ""}</span>
      <div class="toast-body"><div class="toast-title">${this._esc(title)}</div>${msg ? `<div class="toast-msg">${this._esc(msg)}</div>` : ""}</div>
      <button class="toast-close">✕</button>
    `;
    el.querySelector(".toast-close").addEventListener("click", () => el.remove());
    stack.appendChild(el);
    setTimeout(() => el.remove(), 5000);
  }

  _ok(title, msg) { this._toast("success", title, msg); }
  _err(title, msg) { this._toast("error", title, msg); }
  _info(title, msg) { this._toast("info", title, msg); }

  /* ── Live update ─────────────────────────────────────────────────────── */

  _updateLive() {
    const now = Date.now();
    if (!this._lastLiveRender || now - this._lastLiveRender > 5000) {
      this._lastLiveRender = now;
      if (this._view === "main" || this._view.startsWith("plot:")) {
        this._fetchData().then(() => this._renderCurrentView());
      }
    }
  }
}

/* ─── Register ───────────────────────────────────────────────────────────── */

if (!customElements.get("agribuddy-card")) {
  customElements.define("agribuddy-card", AgribuddyCard);
}
window.customCards = window.customCards || [];
if (!window.customCards.some(c => c.type === "agribuddy-card")) {
  window.customCards.push({
    type: "agribuddy-card",
    name: "Agribuddy",
    description: "Garden growth tracker with Daystrom backend, grow plots, plant search, and HA weather integration.",
  });
}
console.info(
  "%c Agribuddy CARD %c v2.0.0 ",
  "background:#1D9E75;color:#fff;font-weight:bold;padding:2px 4px;border-radius:4px 0 0 4px",
  "background:#0F6E56;color:#fff;padding:2px 4px;border-radius:0 4px 4px 0",
);
