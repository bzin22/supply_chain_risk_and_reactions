import fs from "node:fs/promises";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

// Defaults are the original run, so running this with no environment set
// reproduces the first workbook.  SCRISK_EVENT_RETURNS and SCRISK_CHART_OUT
// point it at another run.
const inputPath = process.env.SCRISK_EVENT_RETURNS
  ?? "artifacts/earnings_call_supply_chain/ppmi_svd_full_20260910/earnings_call_event_returns.csv";
const outputDir = process.env.SCRISK_CHART_OUT ?? "outputs/sector_scrisk_rankings";
const outputPath = `${outputDir}/sector_scrisk_rankings.xlsx`;

function parseCsv(text) {
  const rows = [];
  let row = [];
  let cell = "";
  let quoted = false;
  for (let i = 0; i < text.length; i += 1) {
    const char = text[i];
    if (quoted) {
      if (char === '"' && text[i + 1] === '"') {
        cell += '"';
        i += 1;
      } else if (char === '"') {
        quoted = false;
      } else {
        cell += char;
      }
    } else if (char === '"') {
      quoted = true;
    } else if (char === ',') {
      row.push(cell);
      cell = "";
    } else if (char === '\n') {
      row.push(cell.replace(/\r$/, ""));
      rows.push(row);
      row = [];
      cell = "";
    } else {
      cell += char;
    }
  }
  if (cell || row.length) {
    row.push(cell);
    rows.push(row);
  }
  return rows;
}

const csv = await fs.readFile(inputPath, "utf8");
const [header, ...body] = parseCsv(csv);
const fieldIndex = Object.fromEntries(header.map((field, index) => [field, index]));
const value = (row, field) => row[fieldIndex[field]] ?? "";
const number = (text) => {
  const parsed = Number(text);
  return Number.isFinite(parsed) ? parsed : null;
};

const rows = body
  .filter((row) => row.length === header.length && value(row, "SCRisk_sector_rank") !== "")
  .map((row) => ({
    sector: value(row, "sector"),
    rank: number(value(row, "SCRisk_sector_rank")),
    ticker: value(row, "ticker"),
    company: value(row, "company_name"),
    quarter: value(row, "quarter_label"),
    callDate: value(row, "call_date"),
    scrisk: number(value(row, "SCRisk")),
    resolution: number(value(row, "Resolution")),
    car: number(value(row, "CAR_0_1")),
    status: value(row, "event_status"),
  }))
  .sort((a, b) =>
    a.sector.localeCompare(b.sector)
    || a.rank - b.rank
    || b.scrisk - a.scrisk
    || a.ticker.localeCompare(b.ticker)
    || a.quarter.localeCompare(b.quarter));

const workbook = Workbook.create();
const sheet = workbook.worksheets.add("SCRisk rankings");
sheet.showGridLines = false;
sheet.tabColor = "#1F4E78";

sheet.getRange("A2").values = [["SCRisk rankings by sector"]];
sheet.getRange("A3").values = [["One row per ticker-quarter. Lower rank is higher SCRisk; equal scores share a competition rank."]];
sheet.getRange("A2").format.font = { name: "Arial", size: 14, bold: true, color: "#1F1F1F" };
sheet.getRange("A3").format.font = { name: "Arial", size: 10, italic: true, color: "#595959" };

const headers = [
  "Sector", "SCRisk rank", "Ticker", "Company", "Quarter", "Call date",
  "SCRisk", "Resolution", "CAR (0,1)", "CAR status",
];
const startRow = 5;
const data = rows.map((row) => [
  row.sector, row.rank, row.ticker, row.company, row.quarter,
  row.callDate ? new Date(`${row.callDate}T00:00:00Z`) : null,
  row.scrisk, row.resolution, row.car, row.status,
]);
sheet.getRangeByIndexes(startRow - 1, 0, 1, headers.length).values = [headers];
sheet.getRangeByIndexes(startRow, 0, data.length, headers.length).values = data;

const tableRange = `A${startRow}:J${startRow + data.length}`;
sheet.tables.add(tableRange, true);
const headerRange = sheet.getRange(`A${startRow}:J${startRow}`);
headerRange.format.fill = "#1F4E78";
headerRange.format.font = { name: "Arial", size: 10, bold: true, color: "#FFFFFF" };
headerRange.format.horizontalAlignment = "center";
headerRange.format.verticalAlignment = "center";
headerRange.format.rowHeight = 22;

const dataRange = sheet.getRange(`A${startRow + 1}:J${startRow + data.length}`);
dataRange.format.font = { name: "Arial", size: 10, color: "#1F1F1F" };
dataRange.format.verticalAlignment = "center";
sheet.getRange(`B${startRow + 1}:B${startRow + data.length}`).format.horizontalAlignment = "right";
sheet.getRange(`G${startRow + 1}:I${startRow + data.length}`).format.horizontalAlignment = "right";
sheet.getRange(`F${startRow + 1}:F${startRow + data.length}`).format.numberFormat = "yyyy-mm-dd";
sheet.getRange(`G${startRow + 1}:I${startRow + data.length}`).format.numberFormat = "0.0000";

sheet.getRange("A:A").format.columnWidth = 22;
sheet.getRange("B:B").format.columnWidth = 13;
sheet.getRange("C:C").format.columnWidth = 11;
sheet.getRange("D:D").format.columnWidth = 34;
sheet.getRange("E:E").format.columnWidth = 12;
sheet.getRange("F:F").format.columnWidth = 13;
sheet.getRange("G:I").format.columnWidth = 14;
sheet.getRange("J:J").format.columnWidth = 20;
sheet.freezePanes.freezeRows(startRow);
sheet.freezePanes.freezeColumns(2);

workbook.recalculate();
const inspection = await workbook.inspect({
  kind: "table",
  range: "SCRisk rankings!A2:J12",
  include: "values,formulas",
  tableMaxRows: 12,
  tableMaxCols: 10,
});
console.log(inspection.ndjson);
const errors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!",
  options: { useRegex: true, maxResults: 50 },
  summary: "formula error scan",
});
console.log(errors.ndjson);
const render = await workbook.render({ sheetName: "SCRisk rankings", range: "A2:J24", scale: 1.5 });
await fs.mkdir(outputDir, { recursive: true });
await fs.writeFile(`${outputDir}/preview.png`, new Uint8Array(await render.arrayBuffer()));
const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);
console.log(`Wrote ${outputPath} with ${rows.length} ranked events`);
