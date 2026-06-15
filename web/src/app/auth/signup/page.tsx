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
import { Button, Text as OpalText } from "@opal/components";
import { SvgArrowRightCircle, SvgInfo } from "@opal/icons";
import { cn, markdown } from "@opal/utils";
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

  // if user is already logged in, take them to the main app page
  if (currentUser && currentUser.is_active && !currentUser.is_anonymous_user) {
    if (!authTypeMetadata?.requiresVerification || currentUser.is_verified) {
      return redirect("/app");
    }
    return redirect("/auth/waiting-on-verification");
  }
  const cloud = authTypeMetadata?.authType === AuthType.CLOUD;

  if (cloud) {
    return (
      <AuthFlowContainer authState="signup">
        <div className="flex w-full flex-col justify-start gap-6">
          <div className="w-full">
            <OpalText as="h2" font="heading-h2" color="text-05">
              Create account
            </OpalText>
            <OpalText as="p" font="main-ui-body" color="text-03">
              Get started with Onyx
            </OpalText>
          </div>

          <div className="flex w-full gap-3 rounded-16 border border-border-01 bg-background p-4">
            <SvgInfo className="mt-0.5 size-5 shrink-0 text-text-03" />
            <div className="flex min-w-0 flex-col gap-1">
              <OpalText as="p" font="main-ui-action" color="text-04">
                New account creation unavailable.
              </OpalText>
              <OpalText as="p" font="main-ui-body" color="text-03">
                {markdown(
                  "Existing accounts can still [sign in](/auth/login?autoRedirectToSignup=false). New accounts will be available again soon."
                )}
              </OpalText>
              <OpalText as="p" font="main-ui-body" color="text-03">
                {markdown(
                  "You can still try Onyx by [self-hosting](https://docs.onyx.app/deployment/overview)."
                )}
              </OpalText>
            </div>
          </div>

          <Button disabled width="full" rightIcon={SvgArrowRightCircle}>
            Create Account
          </Button>
        </div>
      </AuthFlowContainer>
    );
  }

  // only enable this page if basic login is enabled
  if (authTypeMetadata?.authType !== AuthType.BASIC && !cloud) {
    return redirect("/app");
  }

  let authUrl: string | null = null;
  if (cloud && authTypeMetadata) {
    authUrl = await getAuthUrlSS(authTypeMetadata.authType, null);
  }

  return (
    <AuthFlowContainer authState="signup">
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
                <div className="grow border-t border-border-01" />
                <Text as="p" mainUiMuted text03 className="mx-2">
                  or
                </Text>
                <div className="grow border-t border-border-01" />
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
