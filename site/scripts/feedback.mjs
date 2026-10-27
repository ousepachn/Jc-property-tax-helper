// Print the feedback visitors sent, newest first, as CSV (open it in a spreadsheet).
//   cd site && node --env-file=.env.local scripts/feedback.mjs > feedback.csv
//   node --env-file=.env.local scripts/feedback.mjs --since 2026-11   # one month on
// Needs the AWS_* storage variables `neon deploy` writes into .env.local.
import { Files } from "files-sdk";
import { neon } from "files-sdk/neon";

const files = new Files({ adapter: neon({ bucket: "assets" }) });
const since = process.argv.includes("--since") ? process.argv[process.argv.indexOf("--since") + 1] : "";
const cols = ["received_at", "topic", "address", "pin", "query", "message", "email", "page"];
const rows = [];
for await (const f of files.listAll({ prefix: "feedback/" })) {
  if (since && f.key.slice("feedback/".length) < since) continue;
  rows.push(JSON.parse(await (await files.download(f.key)).text()));
}
rows.sort((a, b) => b.received_at.localeCompare(a.received_at));
const cell = (v) => `"${String(v ?? "").replace(/"/g, '""')}"`;
console.log(cols.join(","));
for (const r of rows) console.log(cols.map((c) => cell(r[c])).join(","));
console.error(`${rows.length} messages`);
