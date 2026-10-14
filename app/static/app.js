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

// 「現在」の日差し：/sunshine の先頭の行（いまの時刻を含む 1 時間。その時刻まで）。
function sunshineTile(sunshine) {
  if (sunshine.status !== "fulfilled" || sunshine.value.hourly.length === 0) {
    return tile("日差し", "", "取得できませんでした");
  }
  const hour = sunshine.value.hourly[0];
  return tile("日差し", sunshineMinutes(hour), `〜${formatTime(hour.time)} の 1 時間`);
}

function renderCurrent(weather, sunshine) {
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
    sunshineTile(sunshine),
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

// 雲底の高さの表示。上限（1,524 m）は「それより下にシーリングがない」なので「—」にする
// （画面の注：「—」は 1,524 m 以上）。
const NO_CEILING = "—";

function formatCeiling(metres) {
  return metres >= CAP_M ? NO_CEILING : `${metres.toLocaleString("ja-JP")} m`;
}

function cloudBaseCell(hour) {
  // その時刻の予測がない（取得できなかった）ときは空欄。理由は表の下に書く。
  return el("td", hour ? formatCeiling(hour.predicted_m) : "", "num");
}

// Promise.allSettled の結果の hourly を、時刻 → 1 時刻ぶんの値にする（失敗なら空）。
function byTime(result) {
  return result.status === "fulfilled"
    ? new Map(result.value.hourly.map((hour) => [hour.time, hour]))
    : new Map();
}

function sunshineMinutes(hour) {
  return `${Math.round(hour.sunshine_s / 60)} 分`;
}

function sunshineCell(hour) {
  // 日照時間（分）と、その下に直達・散乱日射（W/m²）。ない時刻は空欄。
  const cell = el("td", null, "num sun");
  if (!hour) return cell;
  cell.append(
    el("span", sunshineMinutes(hour), "sun-minutes"),
    el(
      "span",
      `直達 ${Math.round(hour.direct_radiation_wm2)} / 散乱 ${Math.round(hour.diffuse_radiation_wm2)} W/m²`,
      "sun-radiation",
    ),
  );
  return cell;
}

function renderSunshineNote(sunshine) {
  document.getElementById("sunshine-note").textContent =
    sunshine.status === "fulfilled"
      ? "日差しは、その時刻までの 1 時間に日が照っていた時間（Open-Meteo の日照時間）と、その 1 時間の平均の日射（水平面）です。雲量が多くても、薄い高層の雲なら日差しが通ることがあります。"
      : "日差し：取得できませんでした";
}

// cloudBaseForecast・sunshine は /cloud-base/forecast・/sunshine の Promise.allSettled の結果。
function renderHourly(weather, cloudBaseForecast, sunshine) {
  const table = document.getElementById("hourly");
  clear(table);
  // 時刻で突き合わせる（/weather の hourly と同じ時刻のはず。ない時刻は空欄）。
  const predictions = byTime(cloudBaseForecast);
  const sun = byTime(sunshine);
  renderSunshineNote(sunshine);
  const note = document.getElementById("hourly-note");
  if (cloudBaseForecast.status === "fulfilled") {
    note.textContent =
      "雲底（予測）は、その時刻の予報値から機械学習モデルで推定した値です（「—」は 1,524 m 以上）。先の時刻ほど予報の誤差が入ります。この使い方の精度は測っていません。";
  } else if (cloudBaseForecast.reason.code === "model_unavailable") {
    note.textContent = "雲底（予測）：モデルを読み込めていません";
  } else {
    note.textContent = "雲底（予測）：取得できませんでした";
  }
  const head = el("tr");
  const names = [
    "時刻",
    "天気",
    "気温",
    "降水確率",
    "降水量",
    "雲量（低 / 中 / 高）",
    "日差し（前の 1 時間）",
    "雲底（予測）",
  ];
  for (const name of names) head.append(el("th", name));
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
      sunshineCell(sun.get(hour.time)),
      cloudBaseCell(predictions.get(hour.time)),
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
  box.append(
    tile("予測", formatCeiling(cloudBase.predicted_m), "機械学習モデル"),
    tile("概算式", formatCeiling(cloudBase.baseline_m), "125 ×（気温 − 露点）"),
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
  // 上限の印は、バーのいちばん上に「—」として付ける。
  const marks = [
    { y: gaugeY(cloudBase.predicted_m), text: `予測 ${formatCeiling(cloudBase.predicted_m)}`, kind: "predicted" },
    { y: gaugeY(cloudBase.baseline_m), text: `概算式 ${formatCeiling(cloudBase.baseline_m)}`, kind: "baseline" },
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

// 折れ線の大きさ（px）。幅は表示している幅に合わせて描き直す（引き伸ばすと線と文字が太るため）。
const LINE_HEIGHT = 150;
const LINE_TOP = 14;
const LINE_BOTTOM = 130;
const PERCENT_TICKS = [0, 25, 50, 75, 100];

// 横の位置は、スライダーのつまみの中心と同じにする（目盛りの時刻と縦のグリッドがそろう）。
function lineX(index, width) {
  return THUMB_PX / 2 + (index * (width - THUMB_PX)) / (history.length - 1);
}

function tickIndexes() {
  const indexes = [];
  for (let index = 0; index < history.length; index += TICK_EVERY) indexes.push(index);
  if (indexes[indexes.length - 1] !== history.length - 1) indexes.push(history.length - 1);
  return indexes;
}

const METRE_TICKS = [0, 500, 1000, CAP_M];

// 折れ線の図を 1 つ描く。values は時刻の順の値（ない時刻は null）。
// capped(value) が真の値は、線でつながず、図のいちばん上に点で出す（雲底の「—」）。
function drawChart(chart, { values, max, ticks, tickLabel, capped }, selected) {
  clear(chart);
  const width = Math.max(chart.clientWidth, 240);
  chart.setAttribute("viewBox", `0 0 ${width} ${LINE_HEIGHT}`);
  chart.setAttribute("height", String(LINE_HEIGHT));
  const x = (index) => lineX(index, width);
  const y = (value) => LINE_BOTTOM - (Math.min(value, max) / max) * (LINE_BOTTOM - LINE_TOP);
  // 横のグリッドと、縦軸の目盛り。文字は線の上の左端に置く。
  for (const tick of ticks) {
    chart.append(svg("line", { x1: 0, y1: y(tick), x2: width, y2: y(tick), class: "grid" }));
    const label = svg("text", { x: 0, y: y(tick) - 3, class: "grid-label" });
    label.textContent = tickLabel(tick);
    chart.append(label);
  }
  // 縦のグリッド（スライダーの目盛りの時刻と同じ位置）。
  for (const index of tickIndexes()) {
    chart.append(svg("line", { x1: x(index), y1: LINE_TOP, x2: x(index), y2: LINE_BOTTOM, class: "grid" }));
  }
  // つながる区間ごとに線を引く。
  let points = [];
  const flush = () => {
    if (points.length > 1) chart.append(svg("polyline", { points: points.join(" "), class: "trend" }));
    else if (points.length === 1) {
      const [cx, cy] = points[0].split(",");
      chart.append(svg("circle", { cx, cy, r: 2.5, class: "trend-dot" }));
    }
    points = [];
  };
  values.forEach((value, index) => {
    if (value === null || capped(value)) {
      flush();
      if (value !== null) chart.append(svg("circle", { cx: x(index), cy: y(max), r: 2.5, class: "capped-dot" }));
      return;
    }
    points.push(`${x(index)},${y(value)}`);
  });
  flush();
  chart.append(svg("line", { x1: x(selected), y1: LINE_TOP, x2: x(selected), y2: LINE_BOTTOM, class: "cursor" }));
  const value = values[selected];
  if (value !== null) {
    chart.append(svg("circle", { cx: x(selected), cy: y(value), r: 4, class: "marker" }));
  }
}

function drawLine(selected) {
  drawChart(
    document.getElementById("history-line"),
    {
      values: history.map((hour) => hour.cloud_cover.total),
      max: 100,
      ticks: PERCENT_TICKS,
      tickLabel: (percent) => `${percent} %`,
      capped: () => false,
    },
    selected,
  );
}

// 過去 24 時間の雲底（/cloud-base/history）。時刻 → 1 時刻ぶんの値。
let ceilingByTime = new Map();

function drawCeiling(selected) {
  const chart = document.getElementById("ceiling-line");
  if (ceilingByTime.size === 0) return;
  drawChart(
    chart,
    {
      values: history.map((hour) => {
        const ceiling = ceilingByTime.get(hour.time);
        return ceiling ? ceiling.predicted_m : null;
      }),
      max: CAP_M,
      ticks: METRE_TICKS,
      tickLabel: (metres) => `${metres.toLocaleString("ja-JP")} m`,
      capped: (metres) => metres >= CAP_M,
    },
    selected,
  );
}

function renderCeilingHistory(result) {
  const error = document.getElementById("ceiling-error");
  const chart = document.getElementById("ceiling-line");
  if (result.status === "fulfilled") {
    ceilingByTime = new Map(result.value.hourly.map((hour) => [hour.time, hour]));
    chart.style.display = "";
    error.hidden = true;
    return;
  }
  ceilingByTime = new Map();
  clear(chart);
  chart.style.display = "none";
  error.textContent =
    result.reason.code === "model_unavailable" ? "モデルを読み込めていません" : "取得できませんでした";
  error.hidden = false;
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
  for (const index of tickIndexes()) {
    const tick = el("span", formatTime(history[index].time), "slider-tick");
    placeOnSlider(tick, index);
    ticks.append(tick);
  }
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
  const ceiling = ceilingByTime.get(hour.time);
  const ceilingText = ceiling ? `・雲底 ${formatCeiling(ceiling.predicted_m)}` : "";
  document.getElementById("history-values").textContent =
    `全体 ${cover.total} %・低 ${cover.low} %・中 ${cover.mid} %・高 ${cover.high} %${ceilingText}`;
  drawSky(cover);
  drawLine(index);
  drawCeiling(index);
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
  const [weather, daylight, cloudBase, cloudHistory, cloudBaseForecast, ceilingHistory, sunshine] =
    await Promise.allSettled([
    getJson("/weather", city),
    getJson("/daylight", city),
    getJson("/cloud-base", city),
    getJson("/cloud-history", city),
    getJson("/cloud-base/forecast", city),
    getJson("/cloud-base/history", city),
    getJson("/sunshine", city),
  ]);
  if (id !== loadId) return;

  // /weather が取れなければ、時刻は UTC で出す。
  timezone = weather.status === "fulfilled" ? weather.value.timezone : "UTC";
  if (weather.status === "fulfilled") {
    const value = weather.value;
    renderCurrent(value, sunshine);
    renderHourly(value, cloudBaseForecast, sunshine);
    renderDaily(value);
    showNotice(value.stale ? `古いデータです（取得：${formatTime(value.fetched_at, true)}）` : "");
  } else {
    for (const name of ["current", "hourly", "daily"]) {
      showError(document.getElementById(name), "取得できませんでした");
    }
    document.getElementById("hourly-note").textContent = "";
    document.getElementById("sunshine-note").textContent = "";
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

  // showHour が雲底の値を使うので、雲量より先に入れる。
  renderCeilingHistory(ceilingHistory);
  if (cloudHistory.status === "fulfilled") renderHistory(cloudHistory.value);
  else failHistory();
}

// 幅が変わったら、折れ線を描き直す。
window.addEventListener("resize", () => {
  if (history.length === 0) return;
  const selected = Number(document.getElementById("history-slider").value);
  drawLine(selected);
  drawCeiling(selected);
});
document.getElementById("history-slider").addEventListener("input", (event) => {
  if (history.length > 0) showHour(Number(event.target.value));
});
for (const button of document.querySelectorAll("[data-city]")) {
  button.addEventListener("click", () => load(button.dataset.city));
}
load("tokyo");
