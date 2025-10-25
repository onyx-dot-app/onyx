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
  if (authTypeMetadata?.authType === "disabled") {
    return redirect("/chat");
  }

  // if user is already logged in, take them to the main app page
  if (currentUser && currentUser.is_active && !currentUser.is_anonymous_user) {
    if (!authTypeMetadata?.requiresVerification || currentUser.is_verified) {
      return redirect("/chat");
    }
    return redirect("/auth/waiting-on-verification");
  }
  const cloud = authTypeMetadata?.authType === "cloud";

  // only enable this page if basic login is enabled
  if (authTypeMetadata?.authType !== "basic" && !cloud) {
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
        <div className="flex w-full flex-col justify-start">
          <div className="w-full">
            <Text headingH2 text05>
              {cloud ? "Complete your sign up" : "Sign Up for Onyx"}
            </Text>
            <Text text03>Get started with Onyx</Text>
          </div>
          {cloud && authUrl && (
            <div className="w-full justify-center mt-spacing-headline">
              <SignInButton authorizeUrl={authUrl} authType="cloud" />
              <div className="flex items-center w-full my-spacing-paragraph">
                <div className="flex-grow border-t border-border-01" />
                <Text mainUiMuted text03 className="mx-spacing-interline">
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
