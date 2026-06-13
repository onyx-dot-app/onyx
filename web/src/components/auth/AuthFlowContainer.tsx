"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";
import { APP_NAME } from "@/lib/brand";

export default function AuthFlowContainer({
  children,
  authState,
  footerContent,
}: {
  children: React.ReactNode;
  authState?: "signup" | "login" | "join";
  footerContent?: React.ReactNode;
}) {
  const t = useTranslations("auth.flow");

  return (
    <div className="p-4 flex flex-col items-center justify-center min-h-screen bg-background">
      <div className="w-full max-w-md flex items-start flex-col bg-background-tint-00 rounded-16 shadow-lg shadow-02 p-6">
        <div className="flex items-center gap-2" aria-label={APP_NAME}>
          <div className="h-11 w-11 rounded-12 bg-theme-primary-05 text-text-inverted-05 flex items-center justify-center text-xl font-bold">
            G
          </div>
          <span className="text-xl font-semibold text-text-05">
            {APP_NAME}
          </span>
        </div>
        <div className="w-full mt-3">{children}</div>
      </div>
      {authState === "login" && (
        <div className="text-sm mt-6 text-center w-full text-text-03 mainUiBody mx-auto">
          {footerContent ?? (
            <>
              {t("newToApp", { appName: APP_NAME })}{" "}
              <Link
                href="/auth/signup"
                className="text-text-05 mainUiAction underline transition-colors duration-200"
              >
                {t("createAccount")}
              </Link>
            </>
          )}
        </div>
      )}
      {authState === "signup" && (
        <div className="text-sm mt-6 text-center w-full text-text-03 mainUiBody mx-auto">
          {t("alreadyHaveAccount")}{" "}
          <Link
            href="/auth/login?autoRedirectToSignup=false"
            className="text-text-05 mainUiAction underline transition-colors duration-200"
          >
            {t("signIn")}
          </Link>
        </div>
      )}
    </div>
  );
}
