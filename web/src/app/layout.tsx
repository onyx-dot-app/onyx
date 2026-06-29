import "./globals.css";

import type { Metadata } from "next";
import { GTM_ENABLED, MODAL_ROOT_ID } from "@/lib/constants";
import { generateFaviconMetadata } from "@/lib/app/svcSS";
import AppProvider from "@/providers/AppProvider";
import { PHProvider } from "./providers";
import {
  PostHogPageTracker,
  PostHogRuntimeInitializer,
  CustomAnalyticsScript,
  WebVitals,
} from "@/lib/analytics/shared";
import Script from "next/script";
import { DM_Mono, Hanken_Grotesk } from "next/font/google";
import { ThemeProvider } from "next-themes";
import { TooltipProvider } from "@radix-ui/react-tooltip";
import StatsOverlayLoader from "@/components/dev/StatsOverlayLoader";
import { cn } from "@opal/utils";
import AppHealthBanner from "@/sections/AppHealthBanner";
import LicenseExpiryBanner from "@/sections/LicenseExpiryBanner";
import ProductGatingWrapper from "@/providers/ProductGatingWrapper";
import SWRConfigProvider from "@/providers/SWRConfigProvider";

const hankenGrotesk = Hanken_Grotesk({
  subsets: ["latin"],
  variable: "--font-hanken-grotesk",
  display: "swap",
  fallback: [
    "-apple-system",
    "BlinkMacSystemFont",
    "Segoe UI",
    "Roboto",
    "sans-serif",
  ],
});

const dmMono = DM_Mono({
  weight: "400",
  subsets: ["latin"],
  variable: "--font-dm-mono",
  display: "swap",
  fallback: [
    "SF Mono",
    "Monaco",
    "Cascadia Code",
    "Roboto Mono",
    "Consolas",
    "Courier New",
    "monospace",
  ],
});

// force-dynamic prevents Next.js from statically prerendering pages at build
// time — many child routes use cookies() which requires dynamic rendering.
export const dynamic = "force-dynamic";

export async function generateMetadata(): Promise<Metadata> {
  return { icons: await generateFaviconMetadata() };
}

interface LayoutProps {
  children: React.ReactNode;
}

export default function Layout({ children }: LayoutProps) {
  return (
    <html
      lang="en"
      className={cn(hankenGrotesk.variable, dmMono.variable)}
      suppressHydrationWarning
    >
      <head>
        <meta
          name="viewport"
          content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=0, interactive-widget=resizes-content"
        />

        {/* Tag <html> as desktop before paint when running inside the Tauri
            wrapper, so the native title-bar reservation in
            css/desktop-titlebar.css engages. Retries briefly in case the Tauri
            globals aren't injected yet at parse time. No-op in a browser. */}
        <Script
          id="onyx-desktop-detector"
          strategy="beforeInteractive"
          dangerouslySetInnerHTML={{
            __html: `
              (function () {
                function mark() {
                  if ('__TAURI_INTERNALS__' in window || '__TAURI__' in window) {
                    document.documentElement.classList.add('onyx-desktop');
                    return true;
                  }
                  return false;
                }
                if (!mark()) {
                  var tries = 0;
                  var timer = setInterval(function () {
                    if (mark() || ++tries > 20) clearInterval(timer);
                  }, 50);
                }
              })();
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

      <body className={`relative font-hanken`}>
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
                  <LicenseExpiryBanner />
                  <AppProvider>
                    <PostHogRuntimeInitializer />
                    <CustomAnalyticsScript />
                    <PostHogPageTracker />
                    <div id={MODAL_ROOT_ID} className="h-screen w-screen">
                      <ProductGatingWrapper>{children}</ProductGatingWrapper>
                    </div>
                    <WebVitals />
                    {process.env.NEXT_PUBLIC_ENABLE_STATS === "true" && (
                      <StatsOverlayLoader />
                    )}
                  </AppProvider>
                </SWRConfigProvider>
              </PHProvider>
            </TooltipProvider>
          </div>
        </ThemeProvider>
      </body>
    </html>
  );
}
