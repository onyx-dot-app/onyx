import "./globals.css";

import {
  fetchEnterpriseSettingsSS,
  fetchSettingsSS,
} from "@/components/settings/lib";
import {
  CUSTOM_ANALYTICS_ENABLED,
  SERVER_SIDE_ONLY__PAID_ENTERPRISE_FEATURES_ENABLED,
} from "@/lib/constants";
import { SettingsProvider } from "@/components/settings/SettingsProvider";
import { Metadata } from "next";
import { buildClientUrl } from "@/lib/utilsSS";
import { Inter } from "next/font/google";
import Head from "next/head";
import { EnterpriseSettings } from "./admin/settings/interfaces";
import { Card } from "@tremor/react";
import { HeaderTitle } from "@/components/header/HeaderTitle";
import { Logo } from "@/components/Logo";
import { UserProvider } from "@/components/user/UserProvider";
import { ProviderContextProvider } from "@/components/chat_search/ProviderContext";


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
  let logoLocation = buildClientUrl("/danswer.ico");
  let enterpriseSettings: EnterpriseSettings | null = null;
  if (SERVER_SIDE_ONLY__PAID_ENTERPRISE_FEATURES_ENABLED) {
    enterpriseSettings = await (await fetchEnterpriseSettingsSS()).json();
    logoLocation =
      enterpriseSettings && enterpriseSettings.use_custom_logo
        ? "/api/enterprise-settings/logo"
        : buildClientUrl("/danswer.ico");
  }

  return {
    title: enterpriseSettings?.application_name ?? "Danswer",
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
  const combinedSettings = await fetchSettingsSS();

  if (!combinedSettings) {
    // Just display a simple full page error if fetching fails.

    return (
      <html lang="en" className={`${inter.variable} font-sans`}>
        <Head>
          <title>Settings Unavailable | Danswer</title>
        </Head>
        <body className="bg-background text-default">
          <div className="flex flex-col items-center justify-center min-h-screen">
            <div className="mb-2 flex items-center max-w-[175px]">
              <HeaderTitle>Danswer</HeaderTitle>
              <Logo height={40} width={40} />
            </div>

            <Card className="p-8 max-w-md">
              <h1 className="text-2xl font-bold mb-4 text-error">Error</h1>
              <p className="text-text-500">
                Your Danswer instance was not configured properly and your
                settings could not be loaded. This could be due to an admin
                configuration issue or an incomplete setup.
              </p>
              <p className="mt-4">
                If you&apos;re an admin, please check{" "}
                <a
                  className="text-link"
                  href="https://docs.danswer.dev/introduction?utm_source=app&utm_medium=error_page&utm_campaign=config_error"
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  our docs
                </a>{" "}
                to see how to configure Danswer properly. If you&apos;re a user,
                please contact your admin to fix this error.
              </p>
              <p className="mt-4">
                For additional support and guidance, you can reach out to our
                community on{" "}
                <a
                  className="text-link"
                  href="https://danswer.ai?utm_source=app&utm_medium=error_page&utm_campaign=config_error"
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  Slack
                </a>
                .
              </p>
            </Card>
          </div>
        </body>
      </html>
    );
  }

  return (
    <html lang="en">
      <Head>
        <meta
          name="viewport"
          content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=0, interactive-widget=resizes-content"
        />
      </Head>

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

      <body className={`relative ${inter.variable} font-sans`}>
        <div
          className={`text-default min-h-screen bg-background ${
            // TODO: remove this once proper dark mode exists
            process.env.THEME_IS_DARK?.toLowerCase() === "true" ? "dark" : ""
          }`}
        >
          <UserProvider>
            <ProviderContextProvider>
              <SettingsProvider settings={combinedSettings}>
                {children}
              </SettingsProvider>
            </ProviderContextProvider>
          </UserProvider>
        </div>
      </body>
    </html>
  );
}
