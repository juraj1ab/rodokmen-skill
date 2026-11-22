// `npm run export-offline`: spustí ../tools/export_offline_html.py prvým funkčným Pythonom 3.
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const script = fileURLToPath(new URL("../../tools/export_offline_html.py", import.meta.url));
const candidates = process.platform === "win32"
  ? [["python"], ["py", "-3"], ["python3"]]
  : [["python3"], ["python"]];

for (const [cmd, ...pre] of candidates) {
  const probe = spawnSync(cmd, [...pre, "-c", "import sys; sys.exit(sys.version_info < (3, 9))"], { stdio: "ignore" });
  if (probe.status !== 0) continue;
  const run = spawnSync(cmd, [...pre, "-I", "-X", "utf8", script, ...process.argv.slice(2)], { stdio: "inherit" });
  process.exit(run.status ?? 1);
}
console.error("Nenašiel sa Python 3.9+ (python, py -3 ani python3).");
process.exit(1);
