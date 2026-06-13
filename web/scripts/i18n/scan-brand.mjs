// 扫描 P0 路径下"用户可见的 Onyx 文案"残留。代码标识符走 ALLOW 白名单忽略。
// 用法（在 web/ 下）：node scripts/i18n/scan-brand.mjs
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, extname } from "node:path";

const TARGETS = [
  "src/app/app",
  "src/app/auth",
  "src/refresh-components",
  "src/providers/DynamicMetadata.tsx",
  "src/refresh-pages/AppPage.tsx",
  "src/sections/agents/AgentCard.tsx",
  "src/sections/app-chrome/AppChrome.tsx",
  "src/sections/cards/SkillCard.tsx",
  "src/sections/input/AppInputBar.tsx",
  "src/sections/input/SharedAppInputBar.tsx",
  "src/sections/modals/AgentViewerModal.tsx",
  "src/sections/sidebar/AccountPopover.tsx",
  "src/sections/sidebar/AppSidebar.tsx",
  "src/sections/sidebar/ChatButton.tsx",
  "src/sections/sidebar/ChatSearchCommandMenu.tsx",
];
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
  "isOnyxCraftEnabled",
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

function targetFiles(target) {
  try {
    const s = statSync(target);
    if (s.isDirectory()) return walk(target);
    if (
      s.isFile() &&
      [".ts", ".tsx"].includes(extname(target)) &&
      !target.includes(".test.") &&
      !target.includes(".stories.")
    ) {
      return [target];
    }
  } catch {
    return [];
  }
  return [];
}

let hits = 0;
for (const target of TARGETS) {
  for (const file of targetFiles(target)) {
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
