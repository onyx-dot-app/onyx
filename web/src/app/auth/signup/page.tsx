import { User } from "@/lib/types";
import { getCurrentUserSS } from "@/lib/users/svcSS";
import { getAuthTypeMetadataSS, getAuthUrlSS } from "@/lib/auth/svcSS";
import { AuthTypeMetadata } from "@/lib/auth/types";
import { redirect } from "next/navigation";
import { EmailPasswordForm, SignInButton } from "@/lib/auth/components";
import AuthFlowContainer from "@/components/auth/AuthFlowContainer";
import ReferralSourceSelector from "./ReferralSourceSelector";
import AuthErrorDisplay from "@/components/auth/AuthErrorDisplay";
import Text from "@/refresh-components/texts/Text";
import { cn } from "@opal/utils";
import { getTranslations } from "next-intl/server";

const Page = async (props: {
  searchParams?: Promise<{ [key: string]: string | string[] | undefined }>;
}) => {
  const t = await getTranslations("auth");
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
  const cloud = authTypeMetadata?.multiTenant === true;

  // No auth metadata (backend unreachable), nothing to render here.
  if (authTypeMetadata?.multiTenant !== false && !cloud) {
    return redirect("/app");
  }

  // Kill switch off: signup is refused by the backend, bounce to login.
  if (!cloud && authTypeMetadata?.passwordAuthEnabled === false) {
    return redirect("/auth/login");
  }

  let authUrl: string | null = null;
  if (cloud && authTypeMetadata) {
    authUrl = await getAuthUrlSS(authTypeMetadata.multiTenant, null);
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
              {cloud
                ? t("signup.cloudSignupHeading.title")
                : t("signup.createAccountHeading.title")}
            </Text>
            <Text as="p" text03>
              {t("signup.subtitle.text")}
            </Text>
          </div>
          {cloud && authUrl && (
            <div className="w-full justify-center mt-6">
              <SignInButton authorizeUrl={authUrl} />
              <div className="flex items-center w-full my-4">
                <div className="grow border-t border-border-01" />
                <Text as="p" mainUiMuted text03 className="mx-2">
                  {t("signup.orDivider.text")}
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
            label="create"
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
