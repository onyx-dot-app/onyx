import { User } from "@/lib/types";
import { getCurrentUserSS } from "@/lib/users/svcSS";
import { getAuthTypeMetadataSS, getAuthUrlSS } from "@/lib/auth/svcSS";
import { AuthTypeMetadata } from "@/lib/auth/types";
import { redirect } from "next/navigation";
import AuthFlowContainer from "@/components/auth/AuthFlowContainer";
import LoginPage from "./LoginPage";

export interface PageProps {
  searchParams?: Promise<{ [key: string]: string | string[] | undefined }>;
}

export default async function Page(props: PageProps) {
  const searchParams = await props.searchParams;
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

  // if there are no users, send self-hosted deployments to signup for
  // initial setup
  if (
    authTypeMetadata &&
    !authTypeMetadata.hasUsers &&
    !autoRedirectToSignupDisabled &&
    authTypeMetadata.multiTenant === false
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
      authUrl = await getAuthUrlSS(authTypeMetadata.multiTenant, nextUrl);
    } catch (e) {
      console.log(`Some fetch failed for the login page - ${e}`);
    }
  }

  return (
    <div className="flex flex-col ">
      <AuthFlowContainer authState="login">
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
