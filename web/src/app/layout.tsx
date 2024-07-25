import "./globals.css";

import { getCombinedSettings } from "@/components/settings/lib";
import { CUSTOM_ANALYTICS_ENABLED } from "@/lib/constants";
import { SettingsProvider } from "@/components/settings/SettingsProvider";
import { Metadata } from "next";
import { buildClientUrl } from "@/lib/utilsSS";
import { Inter } from "next/font/google";


declare global {
  interface Window {
    justLoggedIn: any;
  }
}

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
  display: "swap",
});

export async function generateMetadata(): Promise<Metadata> {
  const dynamicSettings = await getCombinedSettings({ forceRetrieval: true });
  const logoLocation =
    dynamicSettings.enterpriseSettings &&
    dynamicSettings.enterpriseSettings?.use_custom_logo
      ? "/api/enterprise-settings/logo"
      : buildClientUrl("/danswer.ico");

  return {
    title: dynamicSettings.enterpriseSettings?.application_name ?? "Danswer",
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
  const combinedSettings = await getCombinedSettings({});

  return (
    <html lang="en">
      {CUSTOM_ANALYTICS_ENABLED && combinedSettings.customAnalyticsScript && (
        <head>
          <script
            type="text/javascript"
            dangerouslySetInnerHTML={{
              __html: combinedSettings.customAnalyticsScript,
            }}
          />
        </head>
      )}
      <body
        className={`${inter.variable} font-sans text-default bg-background ${
          // TODO: remove this once proper dark mode exists
          process.env.THEME_IS_DARK?.toLowerCase() === "true" ? "dark" : ""
        }`}
      >
        <SettingsProvider settings={combinedSettings}>
          {children}
        </SettingsProvider>
      </body>
    </html>
  );
}
