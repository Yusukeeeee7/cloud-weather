"use strict";

// 画面：同じオリジンの API（/weather・/daylight・/cloud-base・/cloud-history）を呼んで表示する。
// API の値は textContent で入れる（HTML として解釈させない）。
// 時刻は API では UTC。表示のときだけ、都市のタイムゾーン（/weather の timezone）に直す。

const SVG_NS = "http://www.w3.org/2000/svg";
// /cloud-base の上限（docs/spec.md「9. 目的変数」）。1524 は「それより下にシーリングがない」。
const CAP_M = 1524;
// docs/spec.md「天気の分類」。
const WEATHER_LABELS = {
  clear: "快晴",
  partly_cloudy: "晴れ時々曇り",
  cloudy: "曇り",
  fog: "霧",
  drizzle: "霧雨",
  rain: "雨",
  snow: "雪",
  thunderstorm: "雷雨",
  unknown: "不明",
};
const LAYERS = [
  { key: "high", label: "高層", top: 0 },
  { key: "mid", label: "中層", top: 60 },
  { key: "low", label: "低層", top: 120 },
];
// 1 段に並べる雲のかたまりの数。雲量に合わせて見せる数を変える。
const PUFFS = 8;
// スライダーのつまみの幅（style.css の --thumb と同じ）と、目盛りの時刻の間隔（時間）。
const THUMB_PX = 18;
const TICK_EVERY = 6;

let history = [];
let timezone = "UTC";
// 都市を続けて切り替えたとき、古い応答で上書きしない。
let loadId = 0;

function el(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined && text !== null) node.textContent = String(text);
  if (className) node.className = className;
  return node;
}

function svg(tag, attrs) {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [name, value] of Object.entries(attrs)) node.setAttribute(name, String(value));
  return node;
}

function clear(node) {
  node.replaceChildren();
}

async function getJson(path, city) {
  const response = await fetch(`${path}?${new URLSearchParams({ city })}`, {
    headers: { Accept: "application/json" },
  });
  let body = null;
  try {
    body = await response.json();
  } catch {
    body = null;
  }
  if (!response.ok) {
    const error = new Error(`request failed: ${response.status}`);
    error.status = response.status;
    error.code = body && body.error ? body.error.code : null;
    throw error;
  }
  return body;
}

function formatTime(iso, withDate = false) {
  if (!iso) return "—";
  const options = { timeZone: timezone, hour: "2-digit", minute: "2-digit", hourCycle: "h23" };
  if (withDate) Object.assign(options, { month: "numeric", day: "numeric" });
  return new Intl.DateTimeFormat("ja-JP", options).format(new Date(iso));
}

function formatDate(day) {
  // daily の date は現地の日付（YYYY-MM-DD）。日付として読み、曜日を付ける。
  const date = new Date(`${day}T00:00:00Z`);
  return new Intl.DateTimeFormat("ja-JP", {
    timeZone: "UTC",
    month: "numeric",
    day: "numeric",
    weekday: "short",
  }).format(date);
}

function weatherLabel(category) {
  return WEATHER_LABELS[category] || WEATHER_LABELS.unknown;
}

function tile(label, value, sub) {
  const box = el("div", null, "tile");
  box.append(el("span", label, "tile-label"), el("span", value, "tile-value"));
  if (sub) box.append(el("span", sub, "tile-sub"));
  return box;
}

function showError(container, message) {
  clear(container);
  container.append(el("p", message, "error"));
}

function showNotice(text) {
  const notice = document.getElementById("notice");
  notice.textContent = text || "";
  notice.hidden = !text;
}

// --- 各欄 ---

function renderCurrent(weather) {
  const box = document.getElementById("current");
  clear(box);
  const now = weather.current;
  const cover = now.cloud_cover;
  box.append(
    tile("天気", weatherLabel(now.weather), `${formatTime(now.time)} 現在`),
    tile("気温", `${now.temperature_c.toFixed(1)} ℃`, `体感 ${now.apparent_temperature_c.toFixed(1)} ℃`),
    tile("湿度", `${now.relative_humidity} %`, `露点 ${now.dew_point_c.toFixed(1)} ℃`),
    tile("風速", `${now.wind_speed_ms.toFixed(1)} m/s`),
    tile("雲量", `${cover.total} %`, `低 ${cover.low} / 中 ${cover.mid} / 高 ${cover.high}`),
  );
}

function cloudCell(cover) {
  // 全体の雲量と、その下に低・中・高層の雲量。
  const cell = el("td", null, "num cloud");
  cell.append(
    el("span", `${cover.total} %`, "cloud-total"),
    el("span", `低 ${cover.low} / 中 ${cover.mid} / 高 ${cover.high}`, "cloud-layers"),
  );
  return cell;
}

function renderHourly(weather) {
  const table = document.getElementById("hourly");
  clear(table);
  const head = el("tr");
  for (const name of ["時刻", "天気", "気温", "降水確率", "降水量", "雲量（低 / 中 / 高）"]) head.append(el("th", name));
  const thead = el("thead");
  thead.append(head);
  const tbody = el("tbody");
  for (const hour of weather.hourly) {
    const row = el("tr");
    row.append(
      el("td", formatTime(hour.time)),
      el("td", weatherLabel(hour.weather)),
      el("td", `${hour.temperature_c.toFixed(1)} ℃`, "num"),
      el("td", `${hour.precipitation_probability} %`, "num"),
      el("td", `${hour.precipitation_mm.toFixed(1)} mm`, "num"),
      cloudCell(hour.cloud_cover),
    );
    tbody.append(row);
  }
  table.append(thead, tbody);
}

function renderDaily(weather) {
  const table = document.getElementById("daily");
  clear(table);
  const head = el("tr");
  for (const name of ["日付", "天気", "最高", "最低", "降水確率", "降水量"]) head.append(el("th", name));
  const thead = el("thead");
  thead.append(head);
  const tbody = el("tbody");
  for (const day of weather.daily) {
    const row = el("tr");
    row.append(
      el("td", formatDate(day.date)),
      el("td", weatherLabel(day.weather)),
      el("td", `${day.temperature_max_c.toFixed(1)} ℃`, "num"),
      el("td", `${day.temperature_min_c.toFixed(1)} ℃`, "num"),
      el("td", `${day.precipitation_probability_max} %`, "num"),
      el("td", `${day.precipitation_sum_mm.toFixed(1)} mm`, "num"),
    );
    tbody.append(row);
  }
  table.append(thead, tbody);
}

function hours(value) {
  const whole = Math.floor(value);
  const minutes = Math.round((value - whole) * 60);
  return `${whole} 時間 ${minutes} 分`;
}

function renderDaylight(daylight) {
  const box = document.getElementById("daylight");
  clear(box);
  const civil = daylight.twilight.civil;
  box.append(
    tile("日の出", formatTime(daylight.sunrise), `薄明 ${formatTime(civil.dawn)}`),
    tile("日の入り", formatTime(daylight.sunset), `薄明 ${formatTime(civil.dusk)}`),
    tile("昼の長さ", hours(daylight.daylight_hours)),
    tile("暗い時間", hours(daylight.dark_hours), "太陽が −6° より下"),
  );
}

function renderCloudBase(cloudBase) {
  const box = document.getElementById("cloud-base");
  clear(box);
  const predicted =
    cloudBase.predicted_m >= CAP_M
      ? tile("予測", "なし", "1,524 m より下にシーリングなし")
      : tile("予測", `${cloudBase.predicted_m.toLocaleString("ja-JP")} m`);
  box.append(
    predicted,
    tile("概算式", `${cloudBase.baseline_m.toLocaleString("ja-JP")} m`, "125 ×（気温 − 露点）"),
    tile("時刻", formatTime(cloudBase.valid_at), cloudBase.model_version),
  );
}

// 雲底の高さの縦バー。0〜1,524 m の目盛りに、予測と概算式の高さの印を付ける。
const GAUGE = { top: 16, bottom: 184, barX: 64, barWidth: 12, ticks: [0, 500, 1000, CAP_M] };
// 2 つの印のラベルが重ならないための、縦の最小の間隔。
const GAUGE_LABEL_GAP = 16;

function gaugeY(metres) {
  const ratio = Math.min(Math.max(metres, 0), CAP_M) / CAP_M;
  return GAUGE.bottom - ratio * (GAUGE.bottom - GAUGE.top);
}

function drawGauge(cloudBase) {
  const gauge = document.getElementById("cloud-base-gauge");
  clear(gauge);
  gauge.style.display = "";
  gauge.append(
    svg("rect", {
      x: GAUGE.barX,
      y: GAUGE.top,
      width: GAUGE.barWidth,
      height: GAUGE.bottom - GAUGE.top,
      rx: 3,
      class: "gauge-bar",
    }),
  );
  for (const metres of GAUGE.ticks) {
    const y = gaugeY(metres);
    gauge.append(svg("line", { x1: GAUGE.barX - 6, y1: y, x2: GAUGE.barX, y2: y, class: "gauge-tick" }));
    const label = svg("text", { x: GAUGE.barX - 10, y: y + 4, class: "gauge-label" });
    label.textContent = `${metres.toLocaleString("ja-JP")} m`;
    gauge.append(label);
  }
  const predictedText =
    cloudBase.predicted_m >= CAP_M
      ? `予測 ${CAP_M.toLocaleString("ja-JP")} m 以上`
      : `予測 ${cloudBase.predicted_m.toLocaleString("ja-JP")} m`;
  const marks = [
    { y: gaugeY(cloudBase.predicted_m), text: predictedText, kind: "predicted" },
    { y: gaugeY(cloudBase.baseline_m), text: `概算式 ${cloudBase.baseline_m.toLocaleString("ja-JP")} m`, kind: "baseline" },
  ].sort((a, b) => a.y - b.y);
  // ラベルの位置だけをずらす（印はその高さのまま）。
  marks[0].labelY = marks[0].y;
  marks[1].labelY = Math.max(marks[1].y, marks[0].labelY + GAUGE_LABEL_GAP);
  if (marks[1].labelY > GAUGE.bottom + 4) {
    marks[1].labelY = GAUGE.bottom + 4;
    marks[0].labelY = Math.min(marks[0].labelY, marks[1].labelY - GAUGE_LABEL_GAP);
  }
  const right = GAUGE.barX + GAUGE.barWidth;
  for (const mark of marks) {
    gauge.append(
      svg("line", { x1: GAUGE.barX - 2, y1: mark.y, x2: right + 2, y2: mark.y, class: `gauge-mark ${mark.kind}` }),
      svg("polygon", {
        points: `${right + 4},${mark.y} ${right + 12},${mark.y - 5} ${right + 12},${mark.y + 5}`,
        class: `gauge-pointer ${mark.kind}`,
      }),
    );
    const label = svg("text", { x: right + 16, y: mark.labelY + 4, class: `gauge-text ${mark.kind}` });
    label.textContent = mark.text;
    gauge.append(label);
  }
}

function hideGauge() {
  const gauge = document.getElementById("cloud-base-gauge");
  clear(gauge);
  gauge.style.display = "none";
}

// --- 過去 24 時間 ---

function drawSky(cover) {
  const sky = document.getElementById("history-sky");
  clear(sky);
  sky.append(svg("rect", { x: 0, y: 0, width: 320, height: 180, class: "sky-bg" }));
  for (const layer of LAYERS) {
    const percent = cover[layer.key];
    const band = svg("g", { class: `band band-${layer.key}` });
    band.append(svg("line", { x1: 0, y1: layer.top + 60, x2: 320, y2: layer.top + 60, class: "band-line" }));
    // 雲量が多いほど、かたまりの数と濃さを増やす。0 % なら何も描かない。
    const visible = Math.ceil((percent / 100) * PUFFS);
    const opacity = 0.35 + 0.65 * (percent / 100);
    for (let n = 0; n < visible; n += 1) {
      const cx = 40 + n * 36 + (layer.top % 120 === 0 ? 0 : 18);
      const cy = layer.top + 32;
      const puff = svg("g", { class: "puff", "fill-opacity": opacity.toFixed(2) });
      puff.append(
        svg("ellipse", { cx: cx - 10, cy: cy + 4, rx: 14, ry: 9 }),
        svg("ellipse", { cx, cy: cy - 3, rx: 15, ry: 12 }),
        svg("ellipse", { cx: cx + 12, cy: cy + 4, rx: 13, ry: 9 }),
      );
      band.append(puff);
    }
    const label = svg("text", { x: 6, y: layer.top + 16, class: "band-label" });
    label.textContent = `${layer.label} ${percent} %`;
    band.append(label);
    sky.append(band);
  }
}

function drawLine(selected) {
  const line = document.getElementById("history-line");
  clear(line);
  const x = (index) => 8 + (index * (320 - 16)) / (history.length - 1);
  const y = (percent) => 52 - (percent / 100) * 44;
  const points = history.map((hour, index) => `${x(index)},${y(hour.cloud_cover.total)}`).join(" ");
  line.append(
    svg("line", { x1: 8, y1: 52, x2: 312, y2: 52, class: "axis" }),
    svg("polyline", { points, class: "trend" }),
    svg("line", { x1: x(selected), y1: 4, x2: x(selected), y2: 52, class: "cursor" }),
    svg("circle", { cx: x(selected), cy: y(history[selected].cloud_cover.total), r: 4, class: "marker" }),
  );
}

// スライダーのつまみの中心の位置（%）。つまみの幅のぶん、両端は内側に寄る。
function thumbPercent(index) {
  return (index / (history.length - 1)) * 100;
}

function placeOnSlider(node, index) {
  const percent = thumbPercent(index);
  node.style.left = `calc(${percent}% + ${(0.5 - percent / 100) * THUMB_PX}px)`;
}

function renderTicks() {
  const ticks = document.getElementById("history-ticks");
  clear(ticks);
  for (let index = 0; index < history.length; index += TICK_EVERY) {
    const tick = el("span", formatTime(history[index].time), "slider-tick");
    placeOnSlider(tick, index);
    ticks.append(tick);
  }
  const last = el("span", formatTime(history[history.length - 1].time), "slider-tick");
  placeOnSlider(last, history.length - 1);
  ticks.append(last);
}

function showHour(index) {
  const hour = history[index];
  const ago = history.length - 1 - index;
  const bubble = document.getElementById("history-time");
  bubble.textContent = `${formatTime(hour.time, true)}（${ago === 0 ? "最新" : `${ago} 時間前`}）`;
  placeOnSlider(bubble, index);
  bubble.classList.toggle("edge-start", thumbPercent(index) < 20);
  bubble.classList.toggle("edge-end", thumbPercent(index) > 80);
  const cover = hour.cloud_cover;
  document.getElementById("history-values").textContent =
    `全体 ${cover.total} %・低 ${cover.low} %・中 ${cover.mid} %・高 ${cover.high} %`;
  drawSky(cover);
  drawLine(index);
}

function renderHistory(data) {
  history = data.hourly;
  const slider = document.getElementById("history-slider");
  slider.max = String(history.length - 1);
  slider.value = slider.max;
  document.getElementById("history").hidden = false;
  document.getElementById("history-error").hidden = true;
  renderTicks();
  showHour(history.length - 1);
}

function failHistory() {
  history = [];
  document.getElementById("history").hidden = true;
  const error = document.getElementById("history-error");
  error.textContent = "取得できませんでした";
  error.hidden = false;
}

// --- 読み込み ---

async function load(city) {
  const id = (loadId += 1);
  for (const button of document.querySelectorAll("[data-city]")) {
    button.setAttribute("aria-pressed", String(button.dataset.city === city));
  }
  const [weather, daylight, cloudBase, cloudHistory] = await Promise.allSettled([
    getJson("/weather", city),
    getJson("/daylight", city),
    getJson("/cloud-base", city),
    getJson("/cloud-history", city),
  ]);
  if (id !== loadId) return;

  // /weather が取れなければ、時刻は UTC で出す。
  timezone = weather.status === "fulfilled" ? weather.value.timezone : "UTC";
  if (weather.status === "fulfilled") {
    const value = weather.value;
    renderCurrent(value);
    renderHourly(value);
    renderDaily(value);
    showNotice(value.stale ? `古いデータです（取得：${formatTime(value.fetched_at, true)}）` : "");
  } else {
    for (const name of ["current", "hourly", "daily"]) {
      showError(document.getElementById(name), "取得できませんでした");
    }
    showNotice("天気を取得できなかったため、時刻は UTC で表示しています");
  }

  if (daylight.status === "fulfilled") renderDaylight(daylight.value);
  else showError(document.getElementById("daylight"), "取得できませんでした");

  if (cloudBase.status === "fulfilled") {
    renderCloudBase(cloudBase.value);
    drawGauge(cloudBase.value);
  } else {
    hideGauge();
    const message =
      cloudBase.reason.code === "model_unavailable" ? "モデルを読み込めていません" : "取得できませんでした";
    showError(document.getElementById("cloud-base"), message);
  }

  if (cloudHistory.status === "fulfilled") renderHistory(cloudHistory.value);
  else failHistory();
}

document.getElementById("history-slider").addEventListener("input", (event) => {
  if (history.length > 0) showHour(Number(event.target.value));
});
for (const button of document.querySelectorAll("[data-city]")) {
  button.addEventListener("click", () => load(button.dataset.city));
}
load("tokyo");
