"use client";

import { AuthTypeMetadata } from "@/lib/userSS";
import LoginText from "@/app/auth/login/LoginText";
import Link from "next/link";
import SignInButton from "@/app/auth/login/SignInButton";
import EmailPasswordForm from "./EmailPasswordForm";
import { NEXT_PUBLIC_FORGOT_PASSWORD_ENABLED } from "@/lib/constants";
import { useSendAuthRequiredMessage } from "@/lib/extension/utils";
import Text from "@/refresh-components/texts/Text";
import Button from "@/refresh-components/buttons/Button";

interface LoginPageProps {
  authUrl: string | null;
  authTypeMetadata: AuthTypeMetadata | null;
  nextUrl: string | null;
  hidePageRedirect?: boolean;
}

export default function LoginPage({
  authUrl,
  authTypeMetadata,
  nextUrl,
  hidePageRedirect,
}: LoginPageProps) {
  useSendAuthRequiredMessage();

  return (
    <div className="flex flex-col w-full justify-center">
      {authUrl &&
        authTypeMetadata &&
        authTypeMetadata.authType !== "cloud" &&
        // basic auth is handled below w/ the EmailPasswordForm
        authTypeMetadata.authType !== "basic" && (
          <div className="flex flex-col w-full gap-4">
            <LoginText />
            <SignInButton
              authorizeUrl={authUrl}
              authType={authTypeMetadata?.authType}
            />
          </div>
        )}

      {authTypeMetadata?.authType === "cloud" && (
        <div className="w-full justify-center flex flex-col gap-6">
          <LoginText />
          {authUrl && authTypeMetadata && (
            <>
              <SignInButton
                authorizeUrl={authUrl}
                authType={authTypeMetadata?.authType}
              />
              <div className="flex flex-row items-center w-full gap-2">
                <div className="flex-1 border-t border-text-01" />
                <Text text03 mainUiMuted>
                  or
                </Text>
                <div className="flex-1 border-t border-text-01" />
              </div>
            </>
          )}
          <EmailPasswordForm shouldVerify={true} nextUrl={nextUrl} />
          {NEXT_PUBLIC_FORGOT_PASSWORD_ENABLED && (
            <Link href="/auth/forgot-password">
              <Button>Reset Password</Button>
            </Link>
          )}
        </div>
      )}

      {authTypeMetadata?.authType === "basic" && (
        <div className="flex flex-col w-full gap-6">
          <LoginText />

          <EmailPasswordForm nextUrl={nextUrl} />
        </div>
      )}

      {!hidePageRedirect && (
        <p className="text-center mt-4">
          Don&apos;t have an account?{" "}
          <span
            onClick={() => {
              if (typeof window !== "undefined" && window.top) {
                window.top.location.href = "/auth/signup";
              } else {
                window.location.href = "/auth/signup";
              }
            }}
            className="text-link font-medium cursor-pointer"
          >
            Create an account
          </span>
        </p>
      )}
    </div>
  );
}
