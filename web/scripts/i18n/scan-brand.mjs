// 扫描 P0 路径下"用户可见的 Onyx 文案"残留。代码标识符走 ALLOW 白名单忽略。
// 用法（在 web/ 下）：node scripts/i18n/scan-brand.mjs
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, extname } from "node:path";

const ROOTS = ["src/app/app", "src/app/auth", "src/refresh-components"];
const ALLOW = [
  "@onyx-ai",
  "onyxBranded",
  "SvgOnyxLogo",
  "SvgOnyxLogoTyped",
  "SvgOnyxOctagon",
  "OnyxDocument",
  "SearchOnyxDocument",
  "MinimalOnyxDocument",
  "LoadedOnyxDocument",
  "hide_onyx_branding",
  "OnyxInitializingLoader",
  "onyx.ico",
  "@opal/logos",
];

function walk(dir, out = []) {
  let entries;
  try {
    entries = readdirSync(dir);
  } catch {
    return out;
  }
  for (const name of entries) {
    const p = join(dir, name);
    const s = statSync(p);
    if (s.isDirectory()) walk(p, out);
    else if (
      [".ts", ".tsx"].includes(extname(p)) &&
      !name.includes(".test.") &&
      !name.includes(".stories.")
    ) {
      out.push(p);
    }
  }
  return out;
}

let hits = 0;
for (const root of ROOTS) {
  for (const file of walk(root)) {
    const lines = readFileSync(file, "utf8").split("\n");
    lines.forEach((line, i) => {
      if (!/Onyx/.test(line)) return;
      if (ALLOW.some((a) => line.includes(a))) return;
      const trimmed = line.trim();
      if (trimmed.startsWith("//") || trimmed.startsWith("*")) return;
      console.log(`${file}:${i + 1}: ${trimmed}`);
      hits++;
    });
  }
}
console.log(`\n${hits} 处疑似用户可见 "Onyx" 文案残留。`);
process.exit(hits > 0 ? 1 : 0);
