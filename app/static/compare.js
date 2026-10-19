"use strict";

// 気候の比較ページ（#25）：同じオリジンの /static/climate.json を読んで、SVG でグラフを描く。
// JSON は ml/climate.py の climate_summary をノートブック 09 で保存したもの。値は textContent で入れる。

const SVG_NS = "http://www.w3.org/2000/svg";
const CITIES = [
  { key: "tokyo", label: "東京" },
  { key: "berlin", label: "ベルリン" },
];
// 横軸の月（グラフの下に出す）。
const MONTH_LABELS = ["1月", "2月", "3月", "4月", "5月", "6月", "7月", "8月", "9月", "10月", "11月", "12月"];
// ml/climate.py の CLOUD_COVER_BANDS と同じ順。
const CLOUD_BANDS = [
  { key: "0-25", label: "0〜25 %" },
  { key: "25-50", label: "25〜50 %" },
  { key: "50-75", label: "50〜75 %" },
  { key: "75-100", label: "75〜100 %" },
];
// ml/climate.py の WIND_SECTORS の 8 方位（「静穏・不定」は図には描かず、下に書く）。
const WIND_SECTORS = [
  { key: "N", label: "北" },
  { key: "NE", label: "北東" },
  { key: "E", label: "東" },
  { key: "SE", label: "南東" },
  { key: "S", label: "南" },
  { key: "SW", label: "南西" },
  { key: "W", label: "西" },
  { key: "NW", label: "北西" },
];
// グラフの枠（viewBox 640 × 260 の中の、軸の内側）。
const BOX = { left: 48, right: 628, top: 16, bottom: 228 };

function svg(tag, attrs) {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [name, value] of Object.entries(attrs)) {
    node.setAttribute(name, String(value));
  }
  return node;
}

function text(x, y, value, className, anchor = "middle") {
  const node = svg("text", { x, y, class: className, "text-anchor": anchor });
  node.textContent = value;
  return node;
}

function clear(node) {
  while (node.firstChild) {
    node.removeChild(node.firstChild);
  }
}

function el(tag, value, className) {
  const node = document.createElement(tag);
  if (value !== undefined) {
    node.textContent = value;
  }
  if (className) {
    node.className = className;
  }
  return node;
}

function isNumber(value) {
  return typeof value === "number" && Number.isFinite(value);
}

function formatNumber(value, digits) {
  return value.toLocaleString("ja-JP", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

// 目盛りの間隔：範囲をおよそ 5 つに分ける、1・2・5 × 10 の累乗。
function niceStep(span) {
  const rough = span / 5;
  const power = 10 ** Math.floor(Math.log10(rough));
  for (const factor of [1, 2, 5, 10]) {
    if (factor * power >= rough) {
      return factor * power;
    }
  }
  return 10 * power;
}

function scale(values, includeZero) {
  const numbers = values.filter(isNumber);
  let min = Math.min(...numbers, includeZero ? 0 : Infinity);
  let max = Math.max(...numbers, includeZero ? 0 : -Infinity);
  if (min === max) {
    max = min + 1;
  }
  const step = niceStep(max - min);
  min = Math.floor(min / step) * step;
  max = Math.ceil(max / step) * step;
  const ticks = [];
  for (let value = min; value <= max + step / 2; value += step) {
    ticks.push(Number(value.toFixed(6)));
  }
  return { min, max, ticks, step };
}

function yOf(value, range) {
  return BOX.bottom - ((value - range.min) / (range.max - range.min)) * (BOX.bottom - BOX.top);
}

function drawAxes(chart, range, labels, unit) {
  for (const tick of range.ticks) {
    const y = yOf(tick, range);
    chart.append(svg("line", { x1: BOX.left, x2: BOX.right, y1: y, y2: y, class: "grid" }));
    const digits = range.step < 1 ? 1 : 0;
    chart.append(text(BOX.left - 6, y + 4, `${formatNumber(tick, digits)}${unit}`, "grid-label", "end"));
  }
  const width = (BOX.right - BOX.left) / labels.length;
  labels.forEach((label, index) => {
    chart.append(text(BOX.left + width * (index + 0.5), BOX.bottom + 18, label, "grid-label"));
  });
  chart.append(svg("line", { x1: BOX.left, x2: BOX.right, y1: BOX.bottom, y2: BOX.bottom, class: "axis" }));
}

// 折れ線。series は { values, className, dashed }。null の点は線を切る。
function lineChart(chart, labels, series, unit, includeZero) {
  clear(chart);
  const range = scale(series.flatMap((item) => item.values), includeZero);
  drawAxes(chart, range, labels, unit);
  const width = (BOX.right - BOX.left) / labels.length;
  for (const item of series) {
    let path = "";
    item.values.forEach((value, index) => {
      if (!isNumber(value)) {
        path += " ";
        return;
      }
      const x = BOX.left + width * (index + 0.5);
      const y = yOf(value, range);
      const move = path === "" || path.endsWith(" ");
      path += `${move ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
      const dot = svg("circle", { cx: x, cy: y, r: 4, class: `dot ${item.className}` });
      const title = svg("title", {});
      title.textContent = `${item.label} ${labels[index]}：${formatNumber(value, 1)}${unit}`;
      dot.append(title);
      chart.append(dot);
    });
    const line = svg("path", { d: path.trim(), class: `series ${item.className}` });
    if (item.dashed) {
      line.classList.add("dashed");
    }
    chart.insertBefore(line, chart.firstChild);
  }
}

// 都市ごとに並べた棒。series は { values, className, label }。
function barChart(chart, labels, series, unit, digits) {
  clear(chart);
  const range = scale(series.flatMap((item) => item.values), true);
  drawAxes(chart, range, labels, unit);
  const width = (BOX.right - BOX.left) / labels.length;
  const barWidth = (width * 0.7) / series.length;
  series.forEach((item, seriesIndex) => {
    item.values.forEach((value, index) => {
      if (!isNumber(value)) {
        return;
      }
      const x = BOX.left + width * index + width * 0.15 + barWidth * seriesIndex;
      const y = yOf(value, range);
      const bar = svg("rect", {
        x,
        y,
        width: Math.max(barWidth - 2, 1),
        height: Math.max(BOX.bottom - y, 0),
        class: `bar ${item.className}`,
      });
      const title = svg("title", {});
      title.textContent = `${item.label} ${labels[index]}：${formatNumber(value, digits)}${unit}`;
      bar.append(title);
      chart.append(bar);
    });
  });
}

// 円。shares は CLOUD_BANDS の順の割合（0〜1）。
function pieChart(city, shares) {
  const figure = el("figure", undefined, "pie");
  const chart = svg("svg", { viewBox: "0 0 200 200", role: "img", class: "pie-chart" });
  chart.setAttribute("aria-label", `${city.label}の雲量の分布`);
  let angle = -Math.PI / 2;
  CLOUD_BANDS.forEach((band, index) => {
    const share = shares[band.key];
    if (!isNumber(share) || share <= 0) {
      return;
    }
    const end = angle + share * 2 * Math.PI;
    const large = share > 0.5 ? 1 : 0;
    const point = (value) => `${(100 + 90 * Math.cos(value)).toFixed(2)},${(100 + 90 * Math.sin(value)).toFixed(2)}`;
    const d = share >= 0.9999
      ? "M100,10 A90,90 0 1 1 99.99,10 Z"
      : `M100,100 L${point(angle)} A90,90 0 ${large} 1 ${point(end)} Z`;
    const slice = svg("path", { d, class: `slice slice-${index}` });
    const title = svg("title", {});
    title.textContent = `${band.label}：${formatNumber(share * 100, 1)}%`;
    slice.append(title);
    chart.append(slice);
    angle = end;
  });
  figure.append(chart);
  const caption = el("figcaption");
  caption.append(el("strong", city.label));
  const list = el("ul", undefined, "pie-legend");
  CLOUD_BANDS.forEach((band, index) => {
    const share = shares[band.key];
    const item = el("li");
    item.append(el("span", undefined, `key slice-key-${index}`));
    item.append(document.createTextNode(`${band.label}：${isNumber(share) ? formatNumber(share * 100, 1) : "—"}%`));
    list.append(item);
  });
  caption.append(list);
  figure.append(caption);
  return figure;
}

// 風配図。shares は WIND_SECTORS の割合（0〜1）。くさびの長さは max（2 都市で共通）に対する割合。
function roseChart(city, shares, max) {
  const figure = el("figure", undefined, "pie");
  const chart = svg("svg", { viewBox: "0 0 220 220", role: "img", class: "pie-chart" });
  chart.setAttribute("aria-label", `${city.label}の風向の分布`);
  const center = 110;
  const radius = 80;
  for (const ring of [0.5, 1]) {
    chart.append(svg("circle", { cx: center, cy: center, r: radius * ring, class: "rose-ring" }));
  }
  WIND_SECTORS.forEach((sector, index) => {
    const share = shares[sector.key];
    if (!isNumber(share) || share <= 0 || max <= 0) {
      return;
    }
    // 北を上にして時計回り。くさびは方位の中心から ±22.5°（隣と 2° あける）。
    const length = (radius * share) / max;
    const point = (degrees) => {
      const value = ((degrees - 90) * Math.PI) / 180;
      return `${(center + length * Math.cos(value)).toFixed(2)},${(center + length * Math.sin(value)).toFixed(2)}`;
    };
    const wedge = svg("path", {
      d: `M${center},${center} L${point(index * 45 - 21.5)} A${length},${length} 0 0 1 ${point(index * 45 + 21.5)} Z`,
      class: `rose ${city.key}`,
    });
    const title = svg("title", {});
    title.textContent = `${sector.label}：${formatNumber(share * 100, 1)}%`;
    wedge.append(title);
    chart.append(wedge);
  });
  for (const [label, x, y] of [["北", center, 22], ["東", 204, center + 4], ["南", center, 212], ["西", 16, center + 4]]) {
    chart.append(text(x, y, label, "grid-label"));
  }
  figure.append(chart);

  const caption = el("figcaption");
  caption.append(el("strong", city.label));
  const known = WIND_SECTORS.filter((sector) => isNumber(shares[sector.key]));
  const top = known.reduce((best, sector) => (best && shares[best.key] >= shares[sector.key] ? best : sector), null);
  const calm = shares.calm_variable;
  const list = el("ul", undefined, "pie-legend");
  list.append(el("li", top ? `いちばん多い：${top.label}の風（${formatNumber(shares[top.key] * 100, 1)}%）` : "—"));
  list.append(el("li", `静穏・向きの定まらない風：${isNumber(calm) ? formatNumber(calm * 100, 1) : "—"}%`));
  caption.append(list);
  figure.append(caption);
  return figure;
}

function monthly(data, city, name) {
  return data.cities[city.key].monthly.map((row) => row[name]);
}

function render(data) {
  const years = data.cities.tokyo.yearly.map((row) => String(row.year));
  lineChart(
    document.getElementById("temperature-chart"),
    MONTH_LABELS,
    CITIES.flatMap((city) => [
      { label: `${city.label}（実測）`, values: monthly(data, city, "temperature_c_metar"), className: city.key },
      { label: `${city.label}（再解析）`, values: monthly(data, city, "temperature_c_reanalysis"), className: city.key, dashed: true },
    ]),
    "℃",
    false,
  );

  lineChart(
    document.getElementById("dew-chart"),
    MONTH_LABELS,
    CITIES.map((city) => ({ label: city.label, values: monthly(data, city, "dew_point_c_metar"), className: city.key })),
    "℃",
    false,
  );

  lineChart(
    document.getElementById("wind-chart"),
    MONTH_LABELS,
    CITIES.map((city) => ({ label: city.label, values: monthly(data, city, "wind_speed_ms_reanalysis"), className: city.key })),
    "m/s",
    true,
  );

  barChart(
    document.getElementById("yearly-chart"),
    years,
    CITIES.map((city) => ({
      label: city.label,
      values: data.cities[city.key].yearly.map((row) => row.precipitation_mm),
      className: city.key,
    })),
    "",
    0,
  );

  barChart(
    document.getElementById("wet-chart"),
    MONTH_LABELS,
    CITIES.map((city) => ({ label: city.label, values: monthly(data, city, "wet_days_1mm"), className: city.key })),
    "",
    1,
  );

  barChart(
    document.getElementById("observed-chart"),
    MONTH_LABELS,
    CITIES.map((city) => ({
      label: city.label,
      values: monthly(data, city, "precipitation_observed_days"),
      className: city.key,
    })),
    "",
    1,
  );

  const pies = document.getElementById("cloud-charts");
  clear(pies);
  for (const city of CITIES) {
    pies.append(pieChart(city, data.cities[city.key].cloud_cover_share));
  }

  // 2 都市で同じ長さの目盛りにする（比べられるように）。
  const roses = document.getElementById("wind-roses");
  clear(roses);
  const roseMax = Math.max(
    ...CITIES.flatMap((city) =>
      WIND_SECTORS.map((sector) => data.cities[city.key].wind_direction_share[sector.key]).filter(isNumber),
    ),
    0,
  );
  for (const city of CITIES) {
    roses.append(roseChart(city, data.cities[city.key].wind_direction_share, roseMax));
  }

  barChart(
    document.getElementById("star-chart"),
    MONTH_LABELS,
    CITIES.map((city) => ({ label: city.label, values: monthly(data, city, "star_nights"), className: city.key })),
    "",
    1,
  );

  lineChart(
    document.getElementById("ceiling-chart"),
    MONTH_LABELS,
    CITIES.map((city) => ({
      label: city.label,
      values: monthly(data, city, "low_ceiling_share").map((value) => (isNumber(value) ? value * 100 : value)),
      className: city.key,
    })),
    "%",
    true,
  );

  // 雨の日数の、1 年あたりの合計（月ごとの棒を 12 か月ぶん足したもの）。
  const totals = CITIES.map((city) => {
    const total = data.cities[city.key].wet_days_1mm_per_year;
    return `${city.label} ${isNumber(total) ? `${formatNumber(total, 1)} 日` : "—"}`;
  });
  document.getElementById("wet-total").textContent = `1 年あたりの合計：${totals.join("、")}`;

  // 年の数え方（現地の日付）で欠けた日がある年を書く。
  const short = CITIES.flatMap((city) =>
    data.cities[city.key].yearly
      .filter((row) => row.complete_days < daysInYear(row.year))
      .map((row) => `${city.label} ${row.year} 年は ${row.complete_days} 日分`),
  );
  document.getElementById("yearly-note").textContent =
    "現地の日付で区切った、1 時間ごとの値がそろった日の合計です。" +
    (short.length ? `データの端などで日が欠けた年：${short.join("、")}。` : "");

  const auto = data.cities.berlin.yearly
    .map((row) => `${row.year} 年 ${formatNumber(row.metar_auto_share * 100, 0)}%`)
    .join("、");
  document.getElementById("auto-note").textContent =
    `ベルリンの METAR は途中から自動観測（AUTO）に切り替わっています（自動観測の割合：${auto}）。` +
    "人の観測と機械の観測では、雲の報告の仕方が違うことがあります。";
}

function daysInYear(year) {
  return (year % 4 === 0 && year % 100 !== 0) || year % 400 === 0 ? 366 : 365;
}

async function load() {
  const error = document.getElementById("error");
  try {
    const response = await fetch("/static/climate.json");
    if (!response.ok) {
      throw new Error(String(response.status));
    }
    render(await response.json());
  } catch {
    error.textContent = "集計のデータを読み込めませんでした。";
    error.hidden = false;
  }
}

load();
