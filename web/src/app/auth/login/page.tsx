import { User } from "@/lib/types";
import { getCurrentUserSS } from "@/lib/users/svcSS";
import { getAuthTypeMetadataSS, getAuthUrlSS } from "@/lib/auth/svcSS";
import { AuthType, AuthTypeMetadata } from "@/lib/auth/types";
import { NEXT_PUBLIC_AUTH_TYPE } from "@/lib/constants";
import { redirect } from "next/navigation";
import type { Route } from "next";
import AuthFlowContainer from "@/components/auth/AuthFlowContainer";
import LoginPage from "./LoginPage";

export interface PageProps {
  searchParams?: Promise<{ [key: string]: string | string[] | undefined }>;
}

export default async function Page(props: PageProps) {
  const searchParams = await props.searchParams;
  const autoRedirectDisabled = searchParams?.disableAutoRedirect === "true";
  const autoRedirectToSignupDisabled =
    searchParams?.autoRedirectToSignup === "false";
  const nextUrl: string | null = Array.isArray(searchParams?.next)
    ? (searchParams?.next[0] ?? null)
    : (searchParams?.next ?? null);
  const verified = searchParams?.verified === "true";
  const isFirstUser = searchParams?.first_user === "true";

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

  // if there are no users, redirect to signup page for initial setup
  // (only for auth types that support self-service signup)
  if (
    authTypeMetadata &&
    !authTypeMetadata.hasUsers &&
    !autoRedirectToSignupDisabled &&
    NEXT_PUBLIC_AUTH_TYPE === AuthType.BASIC
  ) {
    return redirect("/auth/signup");
  }

  // if user is already logged in, take them to the main app page
  if (currentUser && currentUser.is_active && !currentUser.is_anonymous_user) {
    console.log("Login page: User is logged in, redirecting to chat", {
      userId: currentUser.id,
      is_active: currentUser.is_active,
      is_anonymous: currentUser.is_anonymous_user,
    });

    if (authTypeMetadata?.requiresVerification && !currentUser.is_verified) {
      return redirect("/auth/waiting-on-verification");
    }

    // Add a query parameter to indicate this is a redirect from login
    // This will help prevent redirect loops
    return redirect("/app?from=login");
  }

  // get where to send the user to authenticate
  let authUrl: string | null = null;
  if (authTypeMetadata) {
    try {
      authUrl = await getAuthUrlSS(NEXT_PUBLIC_AUTH_TYPE, nextUrl);
    } catch (e) {
      console.log(`Some fetch failed for the login page - ${e}`);
    }
  }

  if (authTypeMetadata?.autoRedirect && authUrl && !autoRedirectDisabled) {
    return redirect(authUrl as Route);
  }

  const ssoLoginFooterContent =
    authTypeMetadata &&
    (NEXT_PUBLIC_AUTH_TYPE === AuthType.GOOGLE_OAUTH ||
      NEXT_PUBLIC_AUTH_TYPE === AuthType.OIDC ||
      NEXT_PUBLIC_AUTH_TYPE === AuthType.SAML) ? (
      <>Need access? Reach out to your IT admin to get access.</>
    ) : undefined;

  return (
    <div className="flex flex-col ">
      <AuthFlowContainer
        authState="login"
        footerContent={ssoLoginFooterContent}
      >
        <LoginPage
          authUrl={authUrl}
          authTypeMetadata={authTypeMetadata}
          nextUrl={nextUrl}
          hidePageRedirect={true}
          verified={verified}
          isFirstUser={isFirstUser}
        />
      </AuthFlowContainer>
    </div>
  );
}
