"use client";

import { AuthTypeMetadata } from "@/lib/userSS";
import { LoginText } from "./LoginText";
import Link from "next/link";
import { SignInButton } from "./SignInButton";
import { EmailPasswordForm } from "./EmailPasswordForm";
import { NEXT_PUBLIC_FORGOT_PASSWORD_ENABLED } from "@/lib/constants";
import Title from "@/components/ui/title";
import { useSendAuthRequiredMessage } from "@/lib/extension/utils";

export default function LoginPage({
  authUrl,
  authTypeMetadata,
  nextUrl,
  searchParams,
  showPageRedirect,
}: {
  authUrl: string | null;
  authTypeMetadata: AuthTypeMetadata | null;
  nextUrl: string | null;
  searchParams:
    | {
        [key: string]: string | string[] | undefined;
      }
    | undefined;
  showPageRedirect?: boolean;
}) {
  useSendAuthRequiredMessage();
  return (
    <div className="flex flex-col w-full justify-center">
      {authUrl && authTypeMetadata && (
        <>
          <h2 className="text-center text-xl text-strong font-bold">
            <LoginText />
          </h2>

          <SignInButton
            authorizeUrl={authUrl}
            authType={authTypeMetadata?.authType}
          />
        </>
      )}

      {authTypeMetadata?.authType === "cloud" && (
        <div className="mt-4 w-full justify-center">
          <div className="flex items-center w-full my-4">
            <div className="flex-grow border-t border-background-300"></div>
            <span className="px-4 text-text-500">or</span>
            <div className="flex-grow border-t border-background-300"></div>
          </div>
          <EmailPasswordForm shouldVerify={true} nextUrl={nextUrl} />

          <div className="flex mt-4 justify-between">
            <Link
              href={`/auth/signup${
                searchParams?.next ? `?next=${searchParams.next}` : ""
              }`}
              className="text-link font-medium"
            >
              Create an account
            </Link>

            {NEXT_PUBLIC_FORGOT_PASSWORD_ENABLED && (
              <Link
                href="/auth/forgot-password"
                className="text-link font-medium"
              >
                Reset Password
              </Link>
            )}
          </div>
        </div>
      )}

      {authTypeMetadata?.authType === "basic" && (
        <>
          <div className="flex">
            <Title className="mb-2 mx-auto text-xl text-strong font-bold">
              <LoginText />
            </Title>
          </div>
          <EmailPasswordForm nextUrl={nextUrl} />
          <div className="flex flex-col gap-y-2 items-center"></div>
        </>
      )}
      {showPageRedirect && (
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
