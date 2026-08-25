"use client";

import Link from "next/link";
import { SvgOnyxLogo } from "@opal/logos";
import { useSettings } from "@/lib/settings/hooks";
import { Text } from "@opal/components";

export default function AuthFlowContainer({
  children,
  authState,
  footerContent,
}: {
  children: React.ReactNode;
  authState?: "signup" | "login" | "join";
  footerContent?: React.ReactNode;
}) {
  const { appName, logoUrl } = useSettings();
  return (
    <div className="p-4 flex flex-col items-center justify-center min-h-screen bg-background">
      <div className="w-full max-w-md flex items-start flex-col bg-background-tint-00 rounded-16 shadow-lg shadow-box-02 p-6">
        {/* logo_display_style only governs the sidebar; auth pages always show
            the logo mark (custom when uploaded, Onyx otherwise) */}
        {logoUrl ? (
          <div
            className="aspect-square rounded-full overflow-hidden relative"
            style={{ height: 44 }}
          >
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              alt="Logo"
              src={logoUrl}
              className="object-cover object-center w-full h-full"
            />
          </div>
        ) : (
          <SvgOnyxLogo size={44} className="text-theme-primary-05" />
        )}
        <div className="w-full mt-3">{children}</div>
      </div>
      {authState === "login" && (
        <div className="text-sm mt-6 text-center w-full text-text-03 mainUiBody mx-auto">
          {footerContent ?? (
            <>
              <Text font="main-ui-body" color="text-03">
                {`New to ${appName}?`}
              </Text>{" "}
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
            href="/auth/login?autoRedirectToSignup=false"
            className="text-text-05 mainUiAction underline transition-colors duration-200"
          >
            Sign In
          </Link>
        </div>
      )}
    </div>
  );
}
