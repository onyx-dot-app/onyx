import { User } from "@/lib/types";
import {
  getCurrentUserSS,
  getAuthUrlSS,
  getAuthTypeMetadataSS,
  AuthTypeMetadata,
} from "@/lib/userSS";
import { redirect } from "next/navigation";
import type { Route } from "next";
import AuthFlowContainer from "@/refresh-pages/auth/AuthFlowContainer";
import LoginPage from "./LoginPage";
import { AuthType } from "@/lib/constants";
import { markdown } from "@opal/utils";

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

  if (
    authTypeMetadata &&
    !authTypeMetadata.hasUsers &&
    !autoRedirectToSignupDisabled &&
    authTypeMetadata.authType === AuthType.BASIC
  ) {
    return redirect("/auth/signup");
  }

  if (currentUser && currentUser.is_active && !currentUser.is_anonymous_user) {
    console.log("Login page: User is logged in, redirecting to chat", {
      userId: currentUser.id,
      is_active: currentUser.is_active,
      is_anonymous: currentUser.is_anonymous_user,
    });

    if (authTypeMetadata?.requiresVerification && !currentUser.is_verified) {
      return redirect("/auth/waiting-on-verification");
    }

    return redirect("/app?from=login");
  }

  let authUrl: string | null = null;
  if (authTypeMetadata) {
    try {
      authUrl = await getAuthUrlSS(authTypeMetadata.authType, nextUrl);
    } catch (e) {
      console.log(`Some fetch failed for the login page - ${e}`);
    }
  }

  if (authTypeMetadata?.autoRedirect && authUrl && !autoRedirectDisabled) {
    return redirect(authUrl as Route);
  }

  const isSso =
    authTypeMetadata?.authType === AuthType.GOOGLE_OAUTH ||
    authTypeMetadata?.authType === AuthType.OIDC ||
    authTypeMetadata?.authType === AuthType.SAML;

  const bottomPrompt = isSso
    ? "Need access? Reach out to your IT admin to get access."
    : markdown("New to Onyx? [Create an Account](/auth/signup)");

  return (
    <AuthFlowContainer
      title="Sign in"
      description="Welcome back"
      bottomPrompt={bottomPrompt}
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
  );
}
