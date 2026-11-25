import "./globals.css";

import type { Metadata, Viewport } from "next";
import { GTM_ENABLED, MODAL_ROOT_ID } from "@/lib/constants";
import { fetchAppName, generateFaviconMetadata } from "@/lib/app/svcSS";
import AppProvider from "@/providers/AppProvider";
import { PHProvider } from "./providers";
import {
  PostHogPageTracker,
  PostHogRuntimeInitializer,
  CustomAnalyticsScript,
  WebVitals,
} from "@/lib/analytics/shared";
import Script from "next/script";
import {
  Atkinson_Hyperlegible_Next,
  DM_Mono,
  Hanken_Grotesk,
} from "next/font/google";
import localFont from "next/font/local";
import { ThemeProvider } from "next-themes";
import { TooltipProvider } from "@radix-ui/react-tooltip";
import StatsOverlayLoader from "@/components/dev/StatsOverlayLoader";
import AppHealthBanner from "@/sections/banners/HealthBanner";
import BannerQueue from "@/sections/banners/BannerQueue";
import { AuthenticationShell } from "@/lib/auth/components";
import ProductGatingWrapper from "@/providers/ProductGatingWrapper";
import SWRConfigProvider from "@/providers/SWRConfigProvider";
import { NextIntlClientProvider } from "next-intl";
import OpalStringsBridge from "@/i18n/OpalStringsBridge";
import { getLocale, getMessages } from "next-intl/server";
import { DirectionProvider } from "@radix-ui/react-direction";
import { cookies } from "next/headers";
import { htmlDirForLocale, messageLocale, type HtmlDir } from "@/i18n/config";
import {
  APPEARANCE_COOKIE_NAME,
  appearanceAttributes,
  parseAppearanceCookie,
} from "@/lib/appearance/preferences";

// The fallbacks after each loaded font in the --font-* variables on <html>
// below. The per-locale CJK tail (--font-cjk-sans, globals.css) must come
// before the generic, or the generic swallows every CJK codepoint. next/font
// takes only literal options, so the fallbacks live here, not in its
// `fallback` option.
const SANS_FALLBACK =
  "-apple-system, BlinkMacSystemFont, Segoe UI, Roboto, var(--font-cjk-sans), sans-serif";
const MONO_FALLBACK =
  "SF Mono, Monaco, Cascadia Code, Roboto Mono, Consolas, Courier New, var(--font-cjk-sans), monospace";

const hankenGrotesk = Hanken_Grotesk({
  subsets: ["latin"],
  display: "swap",
});

// Interface font options (src/lib/appearance/preferences.ts). Not preloaded: a browser
// downloads a font file only when rendered text uses its family, so users
// who keep the default font never fetch these.
const atkinsonHyperlegibleNext = Atkinson_Hyperlegible_Next({
  style: ["normal", "italic"],
  display: "swap",
  preload: false,
  // next/font has no fallback metrics for this family.
  adjustFontFallback: false,
});

// Unmodified upstream files, SIL Open Font License 1.1 (fonts/opendyslexic/OFL.txt).
const openDyslexic = localFont({
  src: [
    {
      path: "./fonts/opendyslexic/OpenDyslexic-Regular.woff2",
      weight: "400",
      style: "normal",
    },
    {
      path: "./fonts/opendyslexic/OpenDyslexic-Italic.woff2",
      weight: "400",
      style: "italic",
    },
    {
      path: "./fonts/opendyslexic/OpenDyslexic-Bold.woff2",
      weight: "700",
      style: "normal",
    },
    {
      path: "./fonts/opendyslexic/OpenDyslexic-BoldItalic.woff2",
      weight: "700",
      style: "italic",
    },
  ],
  // Scales the glyphs so the cap height and text width come close to Hanken
  // Grotesk at the same font size; line heights and the presets stay as they
  // are. globals.css tightens the spacing.
  declarations: [{ prop: "size-adjust", value: "78%" }],
  display: "swap",
  preload: false,
  // The generated fallback matches the unscaled font, so it would render
  // larger than OpenDyslexic while the font loads.
  adjustFontFallback: false,
});

const dmMono = DM_Mono({
  weight: "400",
  subsets: ["latin"],
  display: "swap",
});

// force-dynamic prevents Next.js from statically prerendering pages at build
// time — many child routes use cookies() which requires dynamic rendering.
export const dynamic = "force-dynamic";

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  interactiveWidget: "resizes-content",
};

export async function generateMetadata(): Promise<Metadata> {
  return {
    title: await fetchAppName(),
    icons: await generateFaviconMetadata(),
  };
}

interface LayoutProps {
  children: React.ReactNode;
}

export default async function Layout({ children }: LayoutProps) {
  // The runtime tag comes from the NEXT_LOCALE cookie, or the workspace
  // default when there is none (see src/i18n/request.ts).
  const locale = await getLocale();
  const messages = await getMessages();
  // <html lang> and the direction drop the numbering extension, which belongs
  // to Intl, not the document. UserProvider refreshes when <html lang> differs
  // from the effective language.
  const language = messageLocale(locale);

  const cookieStore = await cookies();
  // The backend keeps this cookie in step with the saved preferences (see
  // src/lib/appearance/preferences.ts), so the first paint already has the user's fonts.
  const appearance = parseAppearanceCookie(
    cookieStore.get(APPEARANCE_COOKIE_NAME)?.value
  );

  let dir: HtmlDir = htmlDirForLocale(language);
  // Dev-only escape hatch so QA can preview either direction without
  // switching account language: set an "onyx-dir" cookie to "rtl" or
  // "ltr" (with path=/) and reload.
  if (process.env.NODE_ENV === "development") {
    const dirOverride = cookieStore.get("onyx-dir")?.value;
    if (dirOverride === "rtl" || dirOverride === "ltr") {
      dir = dirOverride;
    }
  }

  return (
    <html
      lang={language}
      dir={dir}
      {...appearanceAttributes(appearance)}
      // The app-wide font variables are composed here instead of with
      // next/font's `variable` option: the CJK tail (--font-cjk-sans,
      // globals.css) must vary with the locale, so the loaded-webfont chain
      // and the tail have to be joined in one declaration. The interface and
      // content font variables (tokens.css, globals.css) resolve through
      // these, and Opal text presets, the font-interface/font-sans
      // utilities and app CSS resolve through those.
      style={
        {
          "--font-hanken-grotesk": `${hankenGrotesk.style.fontFamily}, ${SANS_FALLBACK}`,
          "--font-atkinson-hyperlegible-next": `${atkinsonHyperlegibleNext.style.fontFamily}, ${SANS_FALLBACK}`,
          "--font-opendyslexic": `${openDyslexic.style.fontFamily}, ${SANS_FALLBACK}`,
          // The "system" interface font (globals.css).
          "--font-system": `system-ui, ${SANS_FALLBACK}`,
          "--font-dm-mono": `${dmMono.style.fontFamily}, ${MONO_FALLBACK}`,
        } as React.CSSProperties
      }
      suppressHydrationWarning
    >
      <head>
        {/* When running inside the Tauri desktop wrapper on macOS, tag <html>
            as desktop so the native title-bar reservation in
            css/desktop-titlebar.css engages before paint. macOS is the only
            platform with an overlay title bar (traffic lights float over the
            content); Linux and Windows keep native window decorations, so
            reserving the strip there would only push content down. Tauri
            injects its IPC globals via an init script that runs before page
            scripts, so this synchronous check sees them; the class then
            persists across client-side navigations. No-op in a browser. */}
        <Script
          id="onyx-desktop-detector"
          strategy="beforeInteractive"
          dangerouslySetInnerHTML={{
            __html: `
              if (
                ('__TAURI_INTERNALS__' in window || '__TAURI__' in window) &&
                navigator.platform.startsWith('Mac')
              ) {
                document.documentElement.classList.add('onyx-desktop');
              }
            `,
          }}
        />

        {GTM_ENABLED && (
          <Script
            id="google-tag-manager"
            strategy="afterInteractive"
            dangerouslySetInnerHTML={{
              __html: `
               (function(w,d,s,l,i){w[l]=w[l]||[];w[l].push({'gtm.start':
               new Date().getTime(),event:'gtm.js'});var f=d.getElementsByTagName(s)[0],
               j=d.createElement(s),dl=l!='dataLayer'?'&l='+l:'';j.async=true;j.src=
               'https://www.googletagmanager.com/gtm.js?id='+i+dl;f.parentNode.insertBefore(j,f);
               })(window,document,'script','dataLayer','GTM-PZXS36NG');
             `,
            }}
          />
        )}
      </head>

      <body className="relative font-interface">
        <NextIntlClientProvider locale={locale} messages={messages}>
          <OpalStringsBridge>
            {/* Radix reads direction from context, not the DOM, so popovers,
              menus and roving focus need this alongside <html dir>. */}
            <DirectionProvider dir={dir}>
              <ThemeProvider
                attribute="class"
                defaultTheme="system"
                enableSystem
                disableTransitionOnChange
              >
                <div className="text-text min-h-screen bg-background">
                  <TooltipProvider>
                    <PHProvider>
                      <SWRConfigProvider>
                        <AppHealthBanner />
                        <BannerQueue />
                        <AuthenticationShell>
                          <AppProvider>
                            <PostHogRuntimeInitializer />
                            <CustomAnalyticsScript />
                            <PostHogPageTracker />
                            <div
                              id={MODAL_ROOT_ID}
                              className="h-screen w-screen"
                            >
                              <ProductGatingWrapper>
                                {children}
                              </ProductGatingWrapper>
                            </div>
                            <WebVitals />
                            {process.env.NEXT_PUBLIC_ENABLE_STATS ===
                              "true" && <StatsOverlayLoader />}
                          </AppProvider>
                        </AuthenticationShell>
                      </SWRConfigProvider>
                    </PHProvider>
                  </TooltipProvider>
                </div>
              </ThemeProvider>
            </DirectionProvider>
          </OpalStringsBridge>
        </NextIntlClientProvider>
      </body>
    </html>
  );
}
