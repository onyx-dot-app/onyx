"use client";

import { AuthTypeMetadata } from "@/lib/auth/types";
import LoginText from "@/app/auth/login/LoginText";
import ProviderSignInButton from "@/app/auth/login/ProviderSignInButton";
import { SignInButton, EmailPasswordForm } from "@/lib/auth/components";
import { NEXT_PUBLIC_FORGOT_PASSWORD_ENABLED } from "@/lib/constants";
import { useSendAuthRequiredMessage } from "@/lib/extension/hooks";
import Text from "@/refresh-components/texts/Text";
import { Button, MessageCard } from "@opal/components";

interface LoginPageProps {
  authUrl: string | null;
  authTypeMetadata: AuthTypeMetadata | null;
  nextUrl: string | null;
  hidePageRedirect?: boolean;
  verified?: boolean;
  isFirstUser?: boolean;
}

export default function LoginPage({
  authUrl,
  authTypeMetadata,
  nextUrl,
  hidePageRedirect,
  verified,
  isFirstUser,
}: LoginPageProps) {
  useSendAuthRequiredMessage();

  // Honor any existing nextUrl; only default to new team flow for first users with no nextUrl
  const effectiveNextUrl =
    nextUrl ?? (isFirstUser ? "/app?new_team=true" : null);

  const ssoProviders = authTypeMetadata?.ssoProviders ?? [];

  return (
    <div className="flex flex-col w-full justify-center">
      {verified && (
        <MessageCard
          variant="success"
          title="Your email has been verified! Please sign in to continue."
        />
      )}
      {authTypeMetadata?.multiTenant === true && (
        <div className="w-full justify-center flex flex-col gap-6">
          <LoginText />
          {authUrl && authTypeMetadata && (
            <>
              <SignInButton authorizeUrl={authUrl} />
              <div className="flex flex-row items-center w-full gap-2">
                <div className="flex-1 border-t border-text-01" />
                <Text as="p" text03 mainUiMuted>
                  or
                </Text>
                <div className="flex-1 border-t border-text-01" />
              </div>
            </>
          )}
          <EmailPasswordForm
            label="submit"
            shouldVerify={true}
            nextUrl={effectiveNextUrl}
          />
          {NEXT_PUBLIC_FORGOT_PASSWORD_ENABLED && (
            <Button href="/auth/forgot-password">Reset Password</Button>
          )}
        </div>
      )}

      {authTypeMetadata?.multiTenant === false && (
        <div className="flex flex-col w-full gap-6">
          <LoginText />
          {ssoProviders.length > 0 && (
            <>
              <div className="flex flex-col w-full gap-4">
                {ssoProviders.map((provider) => (
                  <ProviderSignInButton
                    key={provider.name}
                    provider={provider}
                    nextUrl={effectiveNextUrl}
                  />
                ))}
              </div>
              <div className="flex flex-row items-center w-full gap-2">
                <div className="flex-1 border-t border-text-01" />
                <Text as="p" text03 mainUiMuted>
                  or
                </Text>
                <div className="flex-1 border-t border-text-01" />
              </div>
            </>
          )}
          <EmailPasswordForm label="submit" nextUrl={effectiveNextUrl} />
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
