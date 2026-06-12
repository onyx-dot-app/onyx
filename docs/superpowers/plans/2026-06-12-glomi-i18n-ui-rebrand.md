# Glomi AI 汉化 + UI 资源替换（P0）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 Glomi AI（Onyx 硬 fork）的 web 前端落地 next-intl「无路由前缀、中文优先」i18n 基础设施，并把品牌从 Onyx 替换为 Glomi AI，先打通 `/auth/login` + `/app` 壳层的核心路径。

**Architecture:** 用 next-intl 的「without i18n routing」模式——locale 由 cookie `NEXT_LOCALE` 决定（默认 `zh`），URL 不带 `/zh` 前缀，不引入 `[locale]` 路由段。纯逻辑（locale 解析、品牌常量、词典校验）抽到 `src/lib/` 下做 jest 单测；Next 专属部分（`request.ts`、layout provider、server action）用 `bun run build` + 渲染测试验证。品牌字符串走 i18n 词典 + `src/lib/brand.ts` 常量，**严禁全局 sed 替换 "Onyx"**（多数是代码标识符）。

**Tech Stack:** Next.js 16.2.6 (App Router, `output: standalone`, `typedRoutes`, force-dynamic root layout)、React 19.2.4、next-intl ^4、bun、jest（unit=node / integration=jsdom 双 project）、ts-jest。

**Branch:** `feat/glomi-i18n-ui-rebrand`

---

## 范围说明（必读）

- **本计划交付一个完整可验证的纵切**：i18n 基础设施 + 品牌替换 + `/auth/login` 全中文（worked example）+ `/app` 壳层抽取（用扫描脚本做完成门）。
- **`app/page.tsx` 是 `redirect("/app")`，无文案**——不需要"落地页汉化"。
- **logo 资源未就绪**：本计划只做**文字品牌 + metadata + 去除 "Powered by Onyx"**；SVG logo 资源到位后单独替换（Task 9 留有定位步骤，不阻塞本计划）。
- **文件落位以适配 jest testMatch**：纯逻辑放 `src/lib/i18n/`（命中 `**/src/lib/**/*.test.ts` 走 node 单测）；next-intl 入口 `request.ts` 放约定的 `src/i18n/`（不单测，靠 build 验证）。

---

## File Structure

**新建：**
- `web/src/lib/i18n/config.ts` — 纯逻辑：locale 常量 + 解析（可单测，无 Next 依赖）
- `web/src/lib/i18n/config.test.ts` — config 单测（node）
- `web/src/lib/i18n/messages.test.ts` — zh/en 词典 key 对齐校验（node）
- `web/src/lib/brand.ts` — 品牌常量（`APP_NAME` 等）
- `web/src/lib/brand.test.ts` — 品牌常量单测（node）
- `web/src/i18n/request.ts` — next-intl `getRequestConfig`（读 cookie → 选词典）
- `web/src/i18n/setLocale.ts` — 切换语言的 server action（写 cookie）
- `web/messages/zh.json` — 中文词典
- `web/messages/en.json` — 英文词典（保留，便于将来出海/切换）
- `web/scripts/i18n/scan-brand.mjs` — 残留 "Onyx" 用户可见文案扫描脚本
- `web/src/app/auth/login/LoginText.test.tsx` — 登录文案渲染测试（jsdom）

**修改：**
- `web/next.config.js` — 用 `createNextIntlPlugin` 包裹（与 `withSentryConfig` 组合）
- `web/src/app/layout.tsx` — 挂 `NextIntlClientProvider` + `<html lang>` 动态 + metadata 改 "Glomi AI"
- `web/src/app/auth/login/LoginText.tsx` — 文案走 i18n + 品牌常量
- `web/src/refresh-components/Logo.tsx` — "Powered by Onyx" → i18n 品牌
- `web/src/app/app/**` — 壳层文案抽取（Task 9，扫描脚本做门）

---

## Task 1: next-intl 安装 + 纯 locale 配置模块

**Files:**
- Modify: `web/package.json`（新增依赖，由 bun 写入）
- Create: `web/src/lib/i18n/config.ts`
- Test: `web/src/lib/i18n/config.test.ts`

- [ ] **Step 1: 安装 next-intl**

在 `web/` 目录运行：

```bash
cd web && bun add next-intl
```

Expected: `package.json` dependencies 出现 `"next-intl": "^4.x"`，`bun.lock` 更新。

- [ ] **Step 2: 写失败测试**

Create `web/src/lib/i18n/config.ts` 之前，先写测试 `web/src/lib/i18n/config.test.ts`：

```ts
import {
  DEFAULT_LOCALE,
  LOCALE_COOKIE,
  SUPPORTED_LOCALES,
  isSupportedLocale,
  resolveLocale,
} from "./config";

describe("i18n config", () => {
  it("defaults to Chinese", () => {
    expect(DEFAULT_LOCALE).toBe("zh");
  });

  it("uses the standard NEXT_LOCALE cookie name", () => {
    expect(LOCALE_COOKIE).toBe("NEXT_LOCALE");
  });

  it("supports zh and en", () => {
    expect(SUPPORTED_LOCALES).toEqual(["zh", "en"]);
  });

  it("recognizes supported locales", () => {
    expect(isSupportedLocale("zh")).toBe(true);
    expect(isSupportedLocale("en")).toBe(true);
    expect(isSupportedLocale("fr")).toBe(false);
    expect(isSupportedLocale(undefined)).toBe(false);
  });

  it("resolves unknown / missing values to the default", () => {
    expect(resolveLocale("en")).toBe("en");
    expect(resolveLocale("fr")).toBe("zh");
    expect(resolveLocale(undefined)).toBe("zh");
  });
});
```

- [ ] **Step 3: 跑测试确认失败**

Run: `cd web && bun run test -- src/lib/i18n/config.test.ts`
Expected: FAIL —「Cannot find module './config'」。

- [ ] **Step 4: 写最小实现**

Create `web/src/lib/i18n/config.ts`:

```ts
// Pure, Next-independent i18n config so it can be unit-tested in the node
// jest project. Keep `next/headers` and other server-only imports OUT of here.

export const SUPPORTED_LOCALES = ["zh", "en"] as const;
export type SupportedLocale = (typeof SUPPORTED_LOCALES)[number];

export const DEFAULT_LOCALE: SupportedLocale = "zh";

// Standard cookie name next-intl / Next conventions use for the active locale.
export const LOCALE_COOKIE = "NEXT_LOCALE";

export function isSupportedLocale(
  value: string | undefined | null
): value is SupportedLocale {
  return value === "zh" || value === "en";
}

export function resolveLocale(value: string | undefined | null): SupportedLocale {
  return isSupportedLocale(value) ? value : DEFAULT_LOCALE;
}
```

- [ ] **Step 5: 跑测试确认通过**

Run: `cd web && bun run test -- src/lib/i18n/config.test.ts`
Expected: PASS（5 个用例全绿）。

- [ ] **Step 6: 提交**

```bash
git add web/package.json web/bun.lock web/src/lib/i18n/config.ts web/src/lib/i18n/config.test.ts
git commit -m "feat(i18n): add next-intl + pure locale config (zh default)"
```

---

## Task 2: 品牌常量

**Files:**
- Create: `web/src/lib/brand.ts`
- Test: `web/src/lib/brand.test.ts`

- [ ] **Step 1: 写失败测试**

Create `web/src/lib/brand.test.ts`:

```ts
import { APP_NAME } from "./brand";

describe("brand", () => {
  it("exposes the Glomi AI app name", () => {
    expect(APP_NAME).toBe("Glomi AI");
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd web && bun run test -- src/lib/brand.test.ts`
Expected: FAIL —「Cannot find module './brand'」。

- [ ] **Step 3: 写实现**

Create `web/src/lib/brand.ts`:

```ts
// Single source of truth for the product brand. Replaces the hardcoded "Onyx"
// fallbacks scattered across the UI. Do NOT global-replace "Onyx" in the
// codebase — most occurrences are identifiers (@onyx-ai/*, SvgOnyxLogo, etc.).
export const APP_NAME = "Glomi AI";
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd web && bun run test -- src/lib/brand.test.ts`
Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add web/src/lib/brand.ts web/src/lib/brand.test.ts
git commit -m "feat(brand): add APP_NAME constant (Glomi AI)"
```

---

## Task 3: 词典 + key 对齐校验

**Files:**
- Create: `web/messages/zh.json`
- Create: `web/messages/en.json`
- Test: `web/src/lib/i18n/messages.test.ts`

- [ ] **Step 1: 建初始词典**

Create `web/messages/zh.json`:

```json
{
  "auth": {
    "title": "欢迎使用 Glomi AI",
    "subtitle": "你的 AI 工作平台"
  },
  "brand": {
    "poweredBy": "由 Glomi AI 提供支持"
  }
}
```

Create `web/messages/en.json`:

```json
{
  "auth": {
    "title": "Welcome to Glomi AI",
    "subtitle": "Your AI platform for work"
  },
  "brand": {
    "poweredBy": "Powered by Glomi AI"
  }
}
```

- [ ] **Step 2: 写 key 对齐测试**

Create `web/src/lib/i18n/messages.test.ts`（用 `fs` 读取，避免 ts-jest 的 JSON 模块解析问题）：

```ts
import { readFileSync } from "node:fs";
import { join } from "node:path";

function loadKeys(locale: string): string[] {
  const raw = readFileSync(
    join(__dirname, "..", "..", "..", "messages", `${locale}.json`),
    "utf8"
  );
  const data = JSON.parse(raw) as Record<string, unknown>;
  const keys: string[] = [];
  const walk = (obj: Record<string, unknown>, prefix: string) => {
    for (const [k, v] of Object.entries(obj)) {
      const path = prefix ? `${prefix}.${k}` : k;
      if (v && typeof v === "object" && !Array.isArray(v)) {
        walk(v as Record<string, unknown>, path);
      } else {
        keys.push(path);
      }
    }
  };
  walk(data, "");
  return keys.sort();
}

describe("message catalogs", () => {
  it("zh and en have identical key sets", () => {
    expect(loadKeys("zh")).toEqual(loadKeys("en"));
  });

  it("are non-empty", () => {
    expect(loadKeys("zh").length).toBeGreaterThan(0);
  });
});
```

- [ ] **Step 3: 跑测试确认通过**

Run: `cd web && bun run test -- src/lib/i18n/messages.test.ts`
Expected: PASS（zh/en key 集合一致）。

> 注：此测试是本计划后续每次新增文案的"护栏"——任何一边漏 key 都会变红。

- [ ] **Step 4: 提交**

```bash
git add web/messages/zh.json web/messages/en.json web/src/lib/i18n/messages.test.ts
git commit -m "feat(i18n): seed zh/en catalogs + key-parity guard test"
```

---

## Task 4: next-intl request 配置 + next.config 接线

**Files:**
- Create: `web/src/i18n/request.ts`
- Modify: `web/next.config.js`

- [ ] **Step 1: 写 request 配置**

Create `web/src/i18n/request.ts`:

```ts
import { getRequestConfig } from "next-intl/server";
import { cookies } from "next/headers";
import { LOCALE_COOKIE, resolveLocale } from "@/lib/i18n/config";

// "Without i18n routing" setup: we ignore the URL and pick the locale from the
// NEXT_LOCALE cookie (default zh). No [locale] segment, no middleware needed.
export default getRequestConfig(async () => {
  const cookieStore = await cookies();
  const locale = resolveLocale(cookieStore.get(LOCALE_COOKIE)?.value);

  return {
    locale,
    messages: (await import(`../../messages/${locale}.json`)).default,
  };
});
```

- [ ] **Step 2: 接入 next.config.js**

Modify `web/next.config.js`。在文件顶部 require 区（现有 `const { withSentryConfig } = require("@sentry/nextjs");` 之后）加入：

```js
const createNextIntlPlugin = require("next-intl/plugin");
const withNextIntl = createNextIntlPlugin("./src/i18n/request.ts");
```

> CJS interop 兜底：若 `bun run build` 报 `createNextIntlPlugin is not a function`，改为 `require("next-intl/plugin").default`。

然后把底部导出（`module.exports = (phase) => { ... return withSentryConfig(...) }`）改为在 Sentry 外层之前先过 next-intl：

```js
module.exports = (phase) => {
  const isDevServer = phase === PHASE_DEVELOPMENT_SERVER;
  return withSentryConfig(
    withNextIntl({
      ...nextConfig,
      reactCompiler: !isDevServer || process.env.ENABLE_REACT_COMPILER === "1",
    }),
    sentryWebpackPluginOptions
  );
};
```

- [ ] **Step 3: 验证构建（关键风险点）**

Run: `cd web && bun run build`
Expected: 构建成功，无 next-intl / Sentry 接线报错。若失败，依据报错调整 `withNextIntl` / `withSentryConfig` 包裹顺序（以构建通过为准），再继续。

> 这是本计划唯一的架构风险点（next-intl × standalone × typedRoutes × Sentry phase-function）。务必在这里跑通再往下。

- [ ] **Step 4: 提交**

```bash
git add web/src/i18n/request.ts web/next.config.js
git commit -m "feat(i18n): wire next-intl request config into next.config"
```

---

## Task 5: layout 注入 Provider + 动态 lang + 品牌 metadata

**Files:**
- Modify: `web/src/app/layout.tsx`

- [ ] **Step 1: 改 metadata 品牌名（消费 `APP_NAME` 常量，保持单一来源）**

在 `web/src/app/layout.tsx` 顶部 imports 区加：

```tsx
import { APP_NAME } from "@/lib/brand";
```

把 `web/src/app/layout.tsx:52-55`：

```tsx
export const metadata: Metadata = {
  title: "Onyx",
  description: "Question answering for your documents",
};
```

改为（`title` 复用 Task 2 的 `APP_NAME`，避免品牌字符串散落）：

```tsx
export const metadata: Metadata = {
  title: APP_NAME,
  description: "你的 AI 工作平台",
};
```

- [ ] **Step 2: 注入 next-intl provider + 动态 lang**

在 `web/src/app/layout.tsx` 顶部 imports 加：

```tsx
import { NextIntlClientProvider } from "next-intl";
import { getLocale, getMessages } from "next-intl/server";
```

把 `RootLayout` 改为 async，并读取 locale/messages（layout 已是 `force-dynamic`，可安全用 cookies 依赖的 server API）：

```tsx
export default async function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const locale = await getLocale();
  const messages = await getMessages();
  return (
    <html
      lang={locale}
      className={cn(hankenGrotesk.variable, dmMono.variable)}
      suppressHydrationWarning
    >
```

把原来 `<html lang="en"` 改为上面的 `lang={locale}`。

然后用 `NextIntlClientProvider` 包住 provider 树。把现有 `<ThemeProvider ...>...</ThemeProvider>`（在 `<body>` 内）整体包进去：

```tsx
      <body className={`relative font-hanken`}>
        <NextIntlClientProvider locale={locale} messages={messages}>
          <ThemeProvider
            attribute="class"
            defaultTheme="system"
            enableSystem
            disableTransitionOnChange
          >
            {/* ...原有内容保持不变... */}
          </ThemeProvider>
        </NextIntlClientProvider>
      </body>
```

> 只新增一层包裹 + 改 `lang` + 改 metadata，**不动**内部 provider 顺序与内容。

- [ ] **Step 3: 验证构建**

Run: `cd web && bun run build`
Expected: 构建成功。`bun run types:check` 也应通过（async layout 合法）。

Run: `cd web && bun run types:check`
Expected: 无新增类型错误。

- [ ] **Step 4: 提交**

```bash
git add web/src/app/layout.tsx
git commit -m "feat(i18n): provide locale+messages in root layout, brand metadata"
```

---

## Task 6: 切换语言的 server action

**Files:**
- Create: `web/src/i18n/setLocale.ts`

- [ ] **Step 1: 写 server action**

Create `web/src/i18n/setLocale.ts`:

```ts
"use server";

import { cookies } from "next/headers";
import { LOCALE_COOKIE, resolveLocale } from "@/lib/i18n/config";

const ONE_YEAR_SECONDS = 60 * 60 * 24 * 365;

// Persists the chosen locale to the NEXT_LOCALE cookie. The next request's
// getRequestConfig (Task 4) reads it and serves the matching catalog.
export async function setLocale(next: string): Promise<void> {
  const cookieStore = await cookies();
  cookieStore.set(LOCALE_COOKIE, resolveLocale(next), {
    path: "/",
    maxAge: ONE_YEAR_SECONDS,
    sameSite: "lax",
  });
}
```

- [ ] **Step 2: 验证构建/类型**

Run: `cd web && bun run types:check`
Expected: 无类型错误。

> P0 不强制做切换 UI——验收时可直接在浏览器 devtools 把 `NEXT_LOCALE` cookie 设为 `en` 验证双向可用。切换器 UI 留待后续。

- [ ] **Step 3: 提交**

```bash
git add web/src/i18n/setLocale.ts
git commit -m "feat(i18n): add setLocale server action (cookie persistence)"
```

---

## Task 7: 登录文案中文化（worked example，确立抽取范式）

**Files:**
- Modify: `web/src/app/auth/login/LoginText.tsx`
- Test: `web/src/app/auth/login/LoginText.test.tsx`

- [ ] **Step 1: 写失败渲染测试**

Create `web/src/app/auth/login/LoginText.test.tsx`（jsdom，内联 messages 避免 JSON 解析依赖）：

```tsx
import { render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import LoginText from "./LoginText";

const messages = {
  auth: { title: "欢迎使用 Glomi AI", subtitle: "你的 AI 工作平台" },
};

describe("LoginText", () => {
  it("renders the Chinese welcome copy", () => {
    render(
      <NextIntlClientProvider locale="zh" messages={messages}>
        <LoginText />
      </NextIntlClientProvider>
    );
    expect(screen.getByText("欢迎使用 Glomi AI")).toBeInTheDocument();
    expect(screen.getByText("你的 AI 工作平台")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd web && bun run test -- src/app/auth/login/LoginText.test.tsx`
Expected: FAIL — 当前组件渲染的是英文「Welcome to Onyx」/「Your open source AI platform for work」。

- [ ] **Step 3: 改组件用 i18n**

Replace `web/src/app/auth/login/LoginText.tsx` 全文为：

```tsx
"use client";

import React from "react";
import { useTranslations } from "next-intl";
import Text from "@/refresh-components/texts/Text";

export default function LoginText() {
  const t = useTranslations("auth");
  return (
    <div className="w-full flex flex-col ">
      <Text as="p" headingH2 text05>
        {t("title")}
      </Text>
      <Text as="p" text03 mainUiMuted>
        {t("subtitle")}
      </Text>
    </div>
  );
}
```

> 注意：移除了对 `enterpriseSettings.application_name`（EE 白标机制）的依赖——C 端硬 fork 直接用品牌词典。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd web && bun run test -- src/app/auth/login/LoginText.test.tsx`
Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add web/src/app/auth/login/LoginText.tsx web/src/app/auth/login/LoginText.test.tsx
git commit -m "feat(i18n): translate login welcome copy, drop EE app_name dep"
```

---

## Task 8: Logo 去除 "Powered by Onyx"

**Files:**
- Modify: `web/src/refresh-components/Logo.tsx`

- [ ] **Step 1: 替换硬编码品牌串**

Modify `web/src/refresh-components/Logo.tsx`。顶部 imports 加：

```tsx
import { useTranslations } from "next-intl";
```

在组件函数体内（`export default function Logo(...) {` 之后、`return` 之前）加：

```tsx
  const t = useTranslations("brand");
```

把第 93 行附近的硬编码：

```tsx
                >
                  Powered by Onyx
                </Text>
```

改为：

```tsx
                >
                  {t("poweredBy")}
                </Text>
```

> 本任务**只**改这一处用户可见字符串。`SvgOnyxLogo`/`SvgOnyxLogoTyped`（来自 `@opal/logos`）是 logo 资源，logo 未就绪前保持不动（见 Task 9 资源替换说明）。`hide_onyx_branding`、`onyxBranded` 等是标识符/EE 开关，不改。

- [ ] **Step 2: 验证构建/类型**

Run: `cd web && bun run types:check`
Expected: 无类型错误。

> Logo 依赖 `useSettingsContext()`，渲染测试需重度 mock，价值低；本任务以构建 + 词典 key 护栏（Task 3 parity 测试已覆盖 `brand.poweredBy` 存在）+ 验收期人工目检为准。

- [ ] **Step 3: 提交**

```bash
git add web/src/refresh-components/Logo.tsx
git commit -m "feat(i18n): replace 'Powered by Onyx' with branded i18n string"
```

---

## Task 9: 残留品牌扫描脚本 + `/app` 壳层文案抽取

**Files:**
- Create: `web/scripts/i18n/scan-brand.mjs`
- Modify: `web/src/app/app/**`（按扫描结果逐文件，复用 Task 7 范式）
- Modify: `web/messages/zh.json` + `web/messages/en.json`（新增 `chat`/`agents`/`common` 等 namespace）

- [ ] **Step 1: 写扫描脚本**

Create `web/scripts/i18n/scan-brand.mjs`:

```js
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
    else if ([".ts", ".tsx"].includes(extname(p))) out.push(p);
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
```

- [ ] **Step 2: 跑扫描，得到待处理清单**

Run: `cd web && node scripts/i18n/scan-brand.mjs`
Expected: 打印若干 `文件:行号: 内容`，退出码 1。这就是 `/app` 壳层 + auth 下需要逐条处理的品牌/文案清单。

- [ ] **Step 3: 逐文件抽取（复用 Task 7 范式）**

对扫描清单里的**每一个**文件，`src/app/app/` 下面向用户的英文文案，以及 `web/src/components/OnyxInitializingLoader.tsx`（启动加载页品牌，spec B.3 点名；该文件不在扫描 ROOTS 内，需手动处理其内部 "Onyx" 文案），按以下固定范式处理（与 Task 7 一致）：

1. 客户端组件（含 `"use client"`）：`import { useTranslations } from "next-intl";`，在组件体内 `const t = useTranslations("<namespace>");`，把 JSX 里英文/品牌串换成 `t("<key>")`。
2. 服务端组件（无 `"use client"`）：`import { getTranslations } from "next-intl/server";`，`const t = await getTranslations("<namespace>");`，组件需为 async。
3. 每新增一个 key，**同时**在 `messages/zh.json` 与 `messages/en.json` 写入（否则 Task 3 的 parity 测试会红）。
4. namespace 约定：`common`（按钮/通用）、`chat`（对话壳/输入框/空态/开场白）、`agents`（智能体列表）、`settings`（设置入口）、`auth`（已建）、`brand`（已建）。

worked example（以登录为模板，已在 Task 7 落地）——其它文件照此办理。

- [ ] **Step 4: 每处理完一批文件，回归测试 + 重扫**

Run: `cd web && bun run test -- src/lib/i18n/messages.test.ts`
Expected: PASS（zh/en key 对齐）。

Run: `cd web && node scripts/i18n/scan-brand.mjs`
Expected: 命中数下降；处理到只剩 ALLOW 白名单内的标识符时，退出码 0。

- [ ] **Step 5: 整体构建验证**

Run: `cd web && bun run build`
Expected: 成功。

- [ ] **Step 6: 提交**

```bash
git add web/scripts/i18n/scan-brand.mjs web/src/app/app web/src/app/auth web/messages web/src/components/OnyxInitializingLoader.tsx
git commit -m "feat(i18n): scan-brand script + extract /app shell core-path copy"
```

> **logo 资源就位后的后续（不阻塞本计划）**：`grep -rn "SvgOnyxLogo" web/lib/opal/src` 定位 SVG 源，替换为 Glomi AI logo；并替换 `web/public/{logo,logo-dark,logotype,logotype-dark}.png`、`web/public/onyx.ico`（favicon）。

---

## Task 10: 终验 + 收尾

**Files:** 无新增（验证 + 收尾提交）

- [ ] **Step 1: 全量单测**

Run: `cd web && bun run test`
Expected: 全绿（含 config / brand / messages parity / LoginText）。

- [ ] **Step 2: 类型 + 构建**

Run: `cd web && bun run types:check && bun run build`
Expected: 均通过；standalone 产物生成。

- [ ] **Step 3: 人工目检（验收标准）**

1. `cd web && bun run start`（或 dev）启动，默认看到**中文**。
2. 访问 `/auth/login`：显示「欢迎使用 Glomi AI」「你的 AI 工作平台」，无 "Onyx"。
3. 访问 `/app`：壳层（侧栏/输入框/空态/开场白/agents 列表）无英文残留、无 "Onyx" 品牌，标题栏/标签页标题为 "Glomi AI"。
4. devtools 把 `NEXT_LOCALE` cookie 设为 `en` 刷新：界面回英文（证明 i18n 双向可用）。
5. `node scripts/i18n/scan-brand.mjs` 退出码 0。

- [ ] **Step 4: 收尾提交（如有目检修补）**

```bash
git add -A
git commit -m "chore(i18n): P0 verification fixes for login + app shell"
```

---

## 验收对照（spec B.9）
- [ ] `bun run build` 通过，standalone 默认中文 — Task 4/5/10
- [ ] 核心路径无英文/无 "Onyx" 品牌残留 — Task 7/9/10 + scan-brand
- [ ] cookie 切 `en` 可回英文 — Task 4/6/10
- [ ] 文案有清晰 namespace/key 约定 + parity 护栏 — Task 3/9
