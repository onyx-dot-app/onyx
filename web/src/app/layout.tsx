import "./globals.css";

import {
  GTM_ENABLED,
  SERVER_SIDE_ONLY__PAID_ENTERPRISE_FEATURES_ENABLED,
  MODAL_ROOT_ID,
} from "@/lib/constants";
import { Metadata } from "next";

import { Inter } from "next/font/google";
import { EnterpriseSettings } from "@/interfaces/settings";
import AppProvider from "@/providers/AppProvider";
import { PHProvider } from "./providers";
import { Suspense } from "react";
import PostHogPageView from "./PostHogPageView";
import Script from "next/script";
import { Hanken_Grotesk } from "next/font/google";
import { WebVitals } from "./web-vitals";
import { ThemeProvider } from "next-themes";
import { TooltipProvider } from "@/components/ui/tooltip";
import StatsOverlayLoader from "@/components/dev/StatsOverlayLoader";
import AppHealthBanner from "@/sections/AppHealthBanner";
import { buildUrl } from "@/lib/utilsSS";
import CustomAnalyticsScript from "@/components/CustomAnalyticsScript";
import ProductGatingWrapper from "@/components/ProductGatingWrapper";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
  display: "swap",
});

const hankenGrotesk = Hanken_Grotesk({
  subsets: ["latin"],
  variable: "--font-hanken-grotesk",
  display: "swap",
});

export async function generateMetadata(): Promise<Metadata> {
  let logoLocation = "/onyx.ico";
  let enterpriseSettings: EnterpriseSettings | null = null;
  if (SERVER_SIDE_ONLY__PAID_ENTERPRISE_FEATURES_ENABLED) {
    try {
      const res = await fetch(buildUrl("/enterprise-settings"), {
        next: { revalidate: 300 },
      });
      if (res.ok) {
        enterpriseSettings = await res.json();
        logoLocation =
          enterpriseSettings && enterpriseSettings.use_custom_logo
            ? "/api/enterprise-settings/logo"
            : "/onyx.ico";
      }
    } catch {
      // Fall back to defaults if fetch fails
    }
  }

  return {
    title: enterpriseSettings?.application_name || "Onyx",
    description: "Question answering for your documents",
    icons: {
      icon: logoLocation,
    },
  };
}

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
      className={`${inter.variable} ${hankenGrotesk.variable}`}
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

      <body className={`relative ${inter.variable} font-hanken`}>
        <ThemeProvider
          attribute="class"
          defaultTheme="system"
          enableSystem
          disableTransitionOnChange
        >
          <div className="text-text min-h-screen bg-background">
            <TooltipProvider>
              <PHProvider>
                <AppHealthBanner />
                <AppProvider>
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
              </PHProvider>
            </TooltipProvider>
          </div>
        </ThemeProvider>
      </body>
    </html>
  );
}
