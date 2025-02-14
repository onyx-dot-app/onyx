import "./globals.css";

import {
  fetchEnterpriseSettingsSS,
  fetchSettingsSS,
} from "@/components/settings/lib";
import {
  CUSTOM_ANALYTICS_ENABLED,
  GTM_ENABLED,
  SERVER_SIDE_ONLY__PAID_ENTERPRISE_FEATURES_ENABLED,
  NEXT_PUBLIC_CLOUD_ENABLED,
} from "@/lib/constants";
import { Metadata } from "next";
import { buildClientUrl } from "@/lib/utilsSS";
import { Inter } from "next/font/google";
import {
  EnterpriseSettings,
  ApplicationStatus,
} from "./admin/settings/interfaces";
import { fetchAssistantData } from "@/lib/chat/fetchAssistantdata";
import { AppProvider } from "@/components/context/AppProvider";
import { PHProvider } from "./providers";
import { getCurrentUserSS } from "@/lib/userSS";
import CardSection from "@/components/admin/CardSection";
import { Suspense } from "react";
import PostHogPageView from "./PostHogPageView";
import Script from "next/script";
import { LogoType } from "@/components/logo/Logo";
import { Hanken_Grotesk } from "next/font/google";
import { WebVitals } from "./web-vitals";
import { ThemeProvider } from "next-themes";
import CloudError from "@/components/errorPages/CloudErrorPage";
import Error from "@/components/errorPages/ErrorPage";
import AccessRestrictedPage from "@/components/errorPages/AccessRestrictedPage";

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
  let logoLocation = buildClientUrl("/onyx.ico");
  let enterpriseSettings: EnterpriseSettings | null = null;
  if (SERVER_SIDE_ONLY__PAID_ENTERPRISE_FEATURES_ENABLED) {
    enterpriseSettings = await (await fetchEnterpriseSettingsSS()).json();
    logoLocation =
      enterpriseSettings && enterpriseSettings.use_custom_logo
        ? "/api/enterprise-settings/logo"
        : buildClientUrl("/onyx.ico");
  }

  return {
    title: enterpriseSettings?.application_name ?? "Onyx",
    description: "Question answering for your documents",
    icons: {
      icon: logoLocation,
    },
  };
}

export const dynamic = "force-dynamic";

export default async function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const [combinedSettings, assistantsData, user] = await Promise.all([
    fetchSettingsSS(),
    fetchAssistantData(),
    getCurrentUserSS(),
  ]);

  const productGating =
    combinedSettings?.settings.application_status ?? ApplicationStatus.ACTIVE;

  const getPageContent = async (content: React.ReactNode) => (
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
        {CUSTOM_ANALYTICS_ENABLED &&
          combinedSettings?.customAnalyticsScript && (
            <script
              type="text/javascript"
              dangerouslySetInnerHTML={{
                __html: combinedSettings.customAnalyticsScript,
              }}
            />
          )}

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
            <PHProvider>{content}</PHProvider>
          </div>
        </ThemeProvider>
      </body>
    </html>
  );

  if (productGating === ApplicationStatus.GATED_ACCESS) {
    return getPageContent(<AccessRestrictedPage />);
  }

  if (!combinedSettings) {
    return getPageContent(
      NEXT_PUBLIC_CLOUD_ENABLED ? <CloudError /> : <Error />
    );
  }

  const { assistants, hasAnyConnectors, hasImageCompatibleModel } =
    assistantsData;

  return getPageContent(
    <AppProvider
      user={user}
      settings={combinedSettings}
      assistants={assistants}
      hasAnyConnectors={hasAnyConnectors}
      hasImageCompatibleModel={hasImageCompatibleModel}
    >
      <Suspense fallback={null}>
        <PostHogPageView />
      </Suspense>
      {children}
      {process.env.NEXT_PUBLIC_POSTHOG_KEY && <WebVitals />}
    </AppProvider>
  );
}
