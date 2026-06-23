"use client";

import Link from "next/link";
import { SvgOnyxLogo } from "@opal/logos";
import { useTranslation } from "react-i18next";
import { useSettings } from "@/lib/settings/hooks";

export default function AuthFlowContainer({
  children,
  authState,
  footerContent,
}: {
  children: React.ReactNode;
  authState?: "signup" | "login" | "join";
  footerContent?: React.ReactNode;
}) {
  const { t } = useTranslation();
  const { appName } = useSettings();

  return (
    <div className="p-4 flex flex-col items-center justify-center min-h-screen bg-background">
      <div className="w-full max-w-md flex items-start flex-col bg-background-tint-00 rounded-16 shadow-lg shadow-02 p-6">
        <SvgOnyxLogo size={44} className="text-theme-primary-05" />
        <div className="w-full mt-3">{children}</div>
      </div>
      {authState === "login" && (
        <div className="text-sm mt-6 text-center w-full text-text-03 mainUiBody mx-auto">
          {footerContent ?? (
            <>
              {t("auth.new_to_onyx", { appName })}{" "}
              <Link
                href="/auth/signup"
                className="text-text-05 mainUiAction underline transition-colors duration-200"
              >
                {t("auth.create_account")}
              </Link>
            </>
          )}
        </div>
      )}
      {authState === "signup" && (
        <div className="text-sm mt-6 text-center w-full text-text-03 mainUiBody mx-auto">
          {t("auth.already_have_account")}{" "}
          <Link
            href="/auth/login?autoRedirectToSignup=false"
            className="text-text-05 mainUiAction underline transition-colors duration-200"
          >
            {t("auth.sign_in")}
          </Link>
        </div>
      )}
    </div>
  );
}
