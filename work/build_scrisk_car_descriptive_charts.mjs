import fs from "node:fs/promises";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

// Defaults are the original run, so running this with no environment set
// reproduces the first workbook.  SCRISK_EVENT_RETURNS and SCRISK_CHART_OUT
// point it at another run.
const inputPath = process.env.SCRISK_EVENT_RETURNS
  ?? "artifacts/earnings_call_supply_chain/ppmi_svd_full_20260910/earnings_call_event_returns.csv";
const outputDir = process.env.SCRISK_CHART_OUT ?? "outputs/scrisk_car_descriptive_charts";
const outputPath = `${outputDir}/scrisk_car_descriptive_charts.xlsx`;

function parseCsv(text) {
  const rows = [];
  let row = [], cell = "", quoted = false;
  for (let i = 0; i < text.length; i += 1) {
    const char = text[i];
    if (quoted) {
      if (char === '"' && text[i + 1] === '"') { cell += '"'; i += 1; }
      else if (char === '"') quoted = false;
      else cell += char;
    } else if (char === '"') quoted = true;
    else if (char === ',') { row.push(cell); cell = ""; }
    else if (char === '\n') { row.push(cell.replace(/\r$/, "")); rows.push(row); row = []; cell = ""; }
    else cell += char;
  }
  if (cell || row.length) { row.push(cell); rows.push(row); }
  return rows;
}

const csv = await fs.readFile(inputPath, "utf8");
const [header, ...body] = parseCsv(csv);
const index = Object.fromEntries(header.map((field, i) => [field, i]));
const get = (row, field) => row[index[field]] ?? "";
const numeric = (value) => Number.isFinite(Number(value)) ? Number(value) : null;
const events = body
  .filter((row) => row.length === header.length && get(row, "event_status") === "ok")
  .map((row) => ({ sector: get(row, "sector"), scrisk: numeric(get(row, "SCRisk")), car: numeric(get(row, "CAR_0_1")) }))
  .filter((row) => row.scrisk !== null && row.car !== null);

const positive = events.filter((row) => row.scrisk > 0).sort((a, b) => a.scrisk - b.scrisk);
const zero = events.filter((row) => row.scrisk === 0);
for (let i = 0; i < positive.length; i += 1) positive[i].group = `Positive Q${Math.min(5, Math.floor(i * 5 / positive.length) + 1)}`;
for (const row of zero) row.group = "Zero SCRisk";
const groups = ["Zero SCRisk", "Positive Q1", "Positive Q2", "Positive Q3", "Positive Q4", "Positive Q5"];

function summary(rows) {
  const values = rows.map((row) => row.car);
  const n = values.length;
  const mean = values.reduce((total, value) => total + value, 0) / n;
  const variance = n > 1 ? values.reduce((total, value) => total + (value - mean) ** 2, 0) / (n - 1) : 0;
  const se = Math.sqrt(variance / n);
  return { n, mean, se, lower: mean - 1.96 * se, upper: mean + 1.96 * se };
}

const groupSummary = groups.map((group) => ({ group, ...summary(events.filter((row) => row.group === group)) }));
const binCount = 99;
const binnedScatter = Array.from({ length: binCount }, (_, bin) => {
  const lower = Math.floor(bin * positive.length / binCount);
  const upper = Math.floor((bin + 1) * positive.length / binCount);
  const slice = positive.slice(lower, upper);
  return {
    logScrisk: slice.reduce((sum, row) => sum + Math.log1p(row.scrisk), 0) / slice.length,
    meanCar: summary(slice).mean,
    n: slice.length,
  };
});

const sectors = [...new Set(events.map((row) => row.sector))].sort();
const sectorSummary = sectors.map((sector) => ({
  sector,
  zero: summary(events.filter((row) => row.sector === sector && row.group === "Zero SCRisk")).mean,
  low: summary(events.filter((row) => row.sector === sector && row.group === "Positive Q1")).mean,
  high: summary(events.filter((row) => row.sector === sector && row.group === "Positive Q5")).mean,
}));

function quantile(values, p) {
  const ordered = [...values].sort((a, b) => a - b);
  const position = (ordered.length - 1) * p;
  const lower = Math.floor(position);
  const upper = Math.ceil(position);
  return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower);
}
const distributionSummary = groups.map((group) => {
  const values = events.filter((row) => row.group === group).map((row) => row.car);
  return [group, quantile(values, 0.05), quantile(values, 0.25), quantile(values, 0.50), quantile(values, 0.75), quantile(values, 0.95)];
});

const workbook = Workbook.create();
const charts = workbook.worksheets.add("Charts");
const data = workbook.worksheets.add("Chart data");
charts.showGridLines = false;
data.showGridLines = false;
charts.tabColor = "#1F4E78";
charts.getRange("A2").values = [["SCRisk and CAR descriptive charts"]];
charts.getRange("A3").values = [["17,848 events with valid CAR. Descriptive summaries only; no association model or regression has been run."]];
charts.getRange("A2").format.font = { name: "Arial", size: 14, bold: true, color: "#1F1F1F" };
charts.getRange("A3").format.font = { name: "Arial", size: 10, italic: true, color: "#595959" };

data.getRange("A1:E1").values = [["SCRisk group", "Events", "Mean CAR (bp)", "95% CI low (bp)", "95% CI high (bp)"]];
data.getRangeByIndexes(1, 0, groupSummary.length, 5).values = groupSummary.map((row) => [row.group, row.n, row.mean * 10000, row.lower * 10000, row.upper * 10000]);
data.getRange("G1:I1").values = [["log(1 + SCRisk)", "Mean CAR (bp)", "Events per bin"]];
data.getRangeByIndexes(1, 6, binnedScatter.length, 3).values = binnedScatter.map((row) => [row.logScrisk, row.meanCar * 10000, row.n]);
data.getRange("K1:N1").values = [["Sector", "Zero SCRisk CAR (bp)", "Positive Q1 CAR (bp)", "Positive Q5 CAR (bp)"]];
data.getRangeByIndexes(1, 10, sectorSummary.length, 4).values = sectorSummary.map((row) => [row.sector, row.zero * 10000, row.low * 10000, row.high * 10000]);
data.getRange("P1:U1").values = [["SCRisk group", "P5 (bp)", "P25 (bp)", "Median (bp)", "P75 (bp)", "P95 (bp)"]];
data.getRangeByIndexes(1, 15, distributionSummary.length, 6).values = distributionSummary.map((row) => [row[0], ...row.slice(1).map((value) => value * 10000)]);

data.getRange("A1:E7").format.borders = { preset: "all", style: "thin", color: "#D9E2F3" };
data.getRange("G1:I100").format.borders = { preset: "all", style: "thin", color: "#D9E2F3" };
data.getRange("K1:N10").format.borders = { preset: "all", style: "thin", color: "#D9E2F3" };
data.getRange("P1:U1").format.borders = { preset: "all", style: "thin", color: "#D9E2F3" };
for (const range of ["A1:E1", "G1:I1", "K1:N1", "P1:U1"]) {
  data.getRange(range).format.fill = "#1F4E78";
  data.getRange(range).format.font = { name: "Arial", size: 10, bold: true, color: "#FFFFFF" };
  data.getRange(range).format.horizontalAlignment = "center";
}
data.getRange("C2:E7").format.numberFormat = "0.0000";
data.getRange("G2:H100").format.numberFormat = "0.0000";
data.getRange("L2:N10").format.numberFormat = "0.0000";
data.getRange("Q2:U7").format.numberFormat = "0.0000";
data.getRange("A:U").format.font = { name: "Arial", size: 10, color: "#1F1F1F" };
data.getRange("A:A").format.columnWidth = 18;
data.getRange("B:B").format.columnWidth = 11;
data.getRange("C:E").format.columnWidth = 13;
data.getRange("G:I").format.columnWidth = 14;
data.getRange("K:K").format.columnWidth = 22;
data.getRange("L:N").format.columnWidth = 14;
data.getRange("P:U").format.columnWidth = 15;
data.freezePanes.freezeRows(1);

const chart1 = charts.charts.add("bar", {
  title: "Mean CAR (bp) by SCRisk group",
  categories: groupSummary.map((row) => row.group),
  series: [{ name: "Mean CAR (bp)", values: groupSummary.map((row) => row.mean * 10000), fill: { type: "solid", color: "#2F75B5" } }],
  hasLegend: false,
  barOptions: { direction: "column", grouping: "clustered" },
  from: { row: 4, col: 0 },
  extent: { widthPx: 600, heightPx: 300 },
});

const chart2 = charts.charts.add("scatter", {
  title: "Binned mean CAR (bp) versus positive SCRisk",
  series: [{ name: "Mean CAR (bp)", xValues: binnedScatter.map((row) => row.logScrisk), values: binnedScatter.map((row) => row.meanCar * 10000), fill: { type: "solid", color: "#70AD47" } }],
  hasLegend: false,
  from: { row: 4, col: 10 },
  extent: { widthPx: 600, heightPx: 300 },
});

const chart3 = charts.charts.add("bar", {
  title: "Mean CAR (bp) by sector and SCRisk group",
  categories: sectorSummary.map((row) => row.sector),
  series: [
    { name: "Zero SCRisk", values: sectorSummary.map((row) => row.zero * 10000), fill: { type: "solid", color: "#2F75B5" } },
    { name: "Positive Q1", values: sectorSummary.map((row) => row.low * 10000), fill: { type: "solid", color: "#ED7D31" } },
    { name: "Positive Q5", values: sectorSummary.map((row) => row.high * 10000), fill: { type: "solid", color: "#70AD47" } },
  ],
  hasLegend: true,
  legend: { position: "top" },
  barOptions: { direction: "column", grouping: "clustered" },
  from: { row: 22, col: 0 },
  extent: { widthPx: 600, heightPx: 320 },
});

const chart4 = charts.charts.add("line", {
  title: "CAR distribution percentiles (bp) by SCRisk group",
  categories: distributionSummary.map((row) => row[0]),
  series: [
    { name: "P5", values: distributionSummary.map((row) => row[1] * 10000), line: { fill: "#2F75B5", style: "solid", width: 2 } },
    { name: "P25", values: distributionSummary.map((row) => row[2] * 10000), line: { fill: "#ED7D31", style: "solid", width: 2 } },
    { name: "Median", values: distributionSummary.map((row) => row[3] * 10000), line: { fill: "#70AD47", style: "solid", width: 2 } },
    { name: "P75", values: distributionSummary.map((row) => row[4] * 10000), line: { fill: "#00B0F0", style: "solid", width: 2 } },
    { name: "P95", values: distributionSummary.map((row) => row[5] * 10000), line: { fill: "#A02B93", style: "solid", width: 2 } },
  ],
  hasLegend: true,
  legend: { position: "top" },
  from: { row: 22, col: 10 },
  extent: { widthPx: 600, heightPx: 320 },
});

workbook.recalculate();
const inspect = await workbook.inspect({
  kind: "table",
  range: "Chart data!A1:N10",
  include: "values,formulas",
  tableMaxRows: 10,
  tableMaxCols: 14,
});
console.log(inspect.ndjson);
const errors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!",
  options: { useRegex: true, maxResults: 50 },
  summary: "formula error scan",
});
console.log(errors.ndjson);
const preview = await workbook.render({ sheetName: "Charts", range: "A2:S40", scale: 1.5 });
await fs.mkdir(outputDir, { recursive: true });
await fs.writeFile(`${outputDir}/preview.png`, new Uint8Array(await preview.arrayBuffer()));
const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);
console.log(`Wrote ${outputPath}; charts=${charts.charts.items.length}`);
