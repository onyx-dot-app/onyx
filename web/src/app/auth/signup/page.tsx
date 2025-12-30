import { HealthCheckBanner } from "@/components/health/healthcheck";
import { User } from "@/lib/types";
import {
  getCurrentUserSS,
  getAuthTypeMetadataSS,
  AuthTypeMetadata,
  getAuthUrlSS,
} from "@/lib/userSS";
import { redirect } from "next/navigation";
import EmailPasswordForm from "../login/EmailPasswordForm";
import SignInButton from "@/app/auth/login/SignInButton";
import AuthFlowContainer from "@/components/auth/AuthFlowContainer";
import ReferralSourceSelector from "./ReferralSourceSelector";
import AuthErrorDisplay from "@/components/auth/AuthErrorDisplay";
import Text from "@/refresh-components/texts/Text";
import { cn } from "@/lib/utils";
import { AuthType } from "@/lib/constants";

const Page = async (props: {
  searchParams?: Promise<{ [key: string]: string | string[] | undefined }>;
}) => {
  const searchParams = await props.searchParams;
  const nextUrl = Array.isArray(searchParams?.next)
    ? searchParams?.next[0]
    : searchParams?.next || null;

  const defaultEmail = Array.isArray(searchParams?.email)
    ? searchParams?.email[0]
    : searchParams?.email || null;

  // catch cases where the backend is completely unreachable here
  // without try / catch, will just raise an exception and the page
  // will not render
  let authTypeMetadata: AuthTypeMetadata | null = null;
  let currentUser: User | null = null;
  try {
    [authTypeMetadata, currentUser] = await Promise.all([
      getAuthTypeMetadataSS(),
      getCurrentUserSS(),
    ]);
  } catch (e) {
    console.log(`Some fetch failed for the login page - ${e}`);
  }

  // simply take the user to the home page if Auth is disabled
  if (authTypeMetadata?.authType === AuthType.DISABLED) {
    return redirect("/chat");
  }

  // if user is already logged in, take them to the main app page
  if (currentUser && currentUser.is_active && !currentUser.is_anonymous_user) {
    if (!authTypeMetadata?.requiresVerification || currentUser.is_verified) {
      return redirect("/chat");
    }
    return redirect("/auth/waiting-on-verification");
  }
  const cloud = authTypeMetadata?.authType === AuthType.CLOUD;

  // only enable this page if basic login is enabled
  if (authTypeMetadata?.authType !== AuthType.BASIC && !cloud) {
    return redirect("/chat");
  }

  let authUrl: string | null = null;
  if (cloud && authTypeMetadata) {
    authUrl = await getAuthUrlSS(authTypeMetadata.authType, null);
  }

  return (
    <AuthFlowContainer authState="signup">
      <HealthCheckBanner />
      <AuthErrorDisplay searchParams={searchParams} />

      <>
        <div className="absolute top-10x w-full"></div>
        <div
          className={cn(
            "flex w-full flex-col justify-start",
            cloud ? "" : "gap-6"
          )}
        >
          <div className="w-full">
            <Text as="p" headingH2 text05>
              {cloud ? "Complete your sign up" : "Create account"}
            </Text>
            <Text as="p" text03>
              Get started with Onyx
            </Text>
          </div>
          {cloud && authUrl && (
            <div className="w-full justify-center mt-6">
              <SignInButton authorizeUrl={authUrl} authType={AuthType.CLOUD} />
              <div className="flex items-center w-full my-4">
                <div className="flex-grow border-t border-border-01" />
                <Text as="p" mainUiMuted text03 className="mx-2">
                  or
                </Text>
                <div className="flex-grow border-t border-border-01" />
              </div>
            </div>
          )}

          {cloud && (
            <>
              <div className="w-full flex flex-col mb-3">
                <ReferralSourceSelector />
              </div>
            </>
          )}

          <EmailPasswordForm
            isSignup
            shouldVerify={authTypeMetadata?.requiresVerification}
            nextUrl={nextUrl}
            defaultEmail={defaultEmail}
          />
        </div>
      </>
    </AuthFlowContainer>
  );
};

export default Page;
