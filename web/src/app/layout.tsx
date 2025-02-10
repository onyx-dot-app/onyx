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
import { EnterpriseSettings, GatingType } from "./admin/settings/interfaces";
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
    combinedSettings?.settings.product_gating ?? GatingType.NONE;

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

  if (!combinedSettings) {
    return getPageContent(
      NEXT_PUBLIC_CLOUD_ENABLED ? <CloudError /> : <Error />
    );
  }

  if (productGating === GatingType.FULL) {
    return getPageContent(
      <div className="flex flex-col items-center justify-center min-h-screen">
        <div className="mb-2 flex items-center max-w-[175px]">
          <LogoType />
        </div>
        <CardSection className="w-full max-w-md">
          <h1 className="text-2xl font-bold mb-4 text-error">
            Access Restricted
          </h1>
          <p className="text-text-500 mb-4">
            We regret to inform you that your access to Onyx has been
            temporarily suspended due to a lapse in your subscription.
          </p>
          <p className="text-text-500 mb-4">
            To reinstate your access and continue benefiting from Onyx&apos;s
            powerful features, please update your payment information.
          </p>
          <p className="text-text-500">
            If you&apos;re an admin, you can resolve this by visiting the
            billing section. For other users, please reach out to your
            administrator to address this matter.
          </p>
        </CardSection>
      </div>
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
