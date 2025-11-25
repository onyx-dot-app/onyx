"use client";

import Link from "next/link";
import { OnyxIcon } from "../icons/icons";
import { useSettingsContext } from "@/components/settings/SettingsProvider";
import { useApplicationName } from "@/lib/hooks/useApplicationName";

export default function AuthFlowContainer({
  children,
  authState,
  footerContent,
}: {
  children: React.ReactNode;
  authState?: "signup" | "login" | "join";
  footerContent?: React.ReactNode;
}) {
  const settings = useSettingsContext();
  const applicationName = useApplicationName();
  const useCustomLogo = settings.enterpriseSettings?.use_custom_logo;

  return (
    <div className="p-4 flex flex-col items-center justify-center min-h-screen bg-background">
      <div className="w-full max-w-md flex items-start flex-col bg-background-tint-00 rounded-16 shadow-lg shadow-02 p-6">
        {useCustomLogo ? (
          <img
            src="/api/enterprise-settings/logo"
            alt="Logo"
            style={{ objectFit: "contain", height: 44, width: 44 }}
          />
        ) : (
          <OnyxIcon size={44} className="text-theme-primary-05" />
        )}
        <div className="w-full mt-3">{children}</div>
      </div>
      {authState === "login" && (
        <div className="text-sm mt-6 text-center w-full text-text-03 mainUiBody mx-auto">
          {footerContent ?? (
            <>
              New to {applicationName}?{" "}
              <Link
                href="/auth/signup"
                className="text-text-05 mainUiAction underline transition-colors duration-200"
              >
                Create an Account
              </Link>
            </>
          )}
        </div>
      )}
      {authState === "signup" && (
        <div className="text-sm mt-6 text-center w-full text-text-03 mainUiBody mx-auto">
          Already have an account?{" "}
          <Link
            href="/auth/login"
            className="text-text-05 mainUiAction underline transition-colors duration-200"
          >
            Sign In
          </Link>
        </div>
      )}
    </div>
  );
}
