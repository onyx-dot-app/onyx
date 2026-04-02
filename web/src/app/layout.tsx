import "./globals.css";

import { GTM_ENABLED, MODAL_ROOT_ID } from "@/lib/constants";
import { Metadata } from "next";

import AppProvider from "@/providers/AppProvider";
import DynamicMetadata from "@/providers/DynamicMetadata";
import { PHProvider } from "./providers";
import { Suspense } from "react";
import PostHogPageView from "./PostHogPageView";
import Script from "next/script";
import { DM_Mono, Hanken_Grotesk } from "next/font/google";
import { WebVitals } from "./web-vitals";
import { ThemeProvider } from "next-themes";
import { TooltipProvider } from "@/components/ui/tooltip";
import StatsOverlayLoader from "@/components/dev/StatsOverlayLoader";
import AppHealthBanner from "@/sections/AppHealthBanner";
import CustomAnalyticsScript from "@/providers/CustomAnalyticsScript";
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

export const metadata: Metadata = {
  title: "Onyx",
  description: "Question answering for your documents",
};

// force-dynamic prevents Next.js from statically prerendering pages at build
// time — many child routes use cookies() which requires dynamic rendering.
// This is safe because the layout itself has no server-side data fetching;
// all data is fetched client-side via SWR in the provider tree.
export const dynamic = "force-dynamic";

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html
      lang="en"
      className={`${hankenGrotesk.variable} ${dmMono.variable}`}
      suppressHydrationWarning
    >
      <head>
        <meta
          name="viewport"
          content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=0, interactive-widget=resizes-content"
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
                  <AppProvider>
                    <DynamicMetadata />
                    <CustomAnalyticsScript />
                    <Suspense fallback={null}>
                      <PostHogPageView />
                    </Suspense>
                    <div id={MODAL_ROOT_ID} className="h-screen w-screen">
                      <ProductGatingWrapper>{children}</ProductGatingWrapper>
                    </div>
                    {process.env.NEXT_PUBLIC_POSTHOG_KEY && <WebVitals />}
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
