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
import AuthPanelIntro from "@/components/auth/AuthPanelIntro";
import AuthFlowContainer from "@/components/auth/AuthFlowContainer";
import ReferralSourceSelector from "./ReferralSourceSelector";
import AuthErrorDisplay from "@/components/auth/AuthErrorDisplay";
import { cn } from "@/lib/utils";
import { AuthType, DEFAULT_APPLICATION_NAME } from "@/lib/constants";

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
          <AuthPanelIntro
            eyebrow="Cuenta"
            description={`Empieza con ${DEFAULT_APPLICATION_NAME} y entra a un flujo de trabajo con evidencia, decisiones y ejecucion.`}
          >
            {cloud ? "Completa tu registro" : "Crea tu cuenta"}
          </AuthPanelIntro>
          {cloud && authUrl && (
            <div className="w-full justify-center mt-6">
              <SignInButton authorizeUrl={authUrl} authType={AuthType.CLOUD} />
              <div className="flex items-center w-full my-4">
                <div className="flex-grow border-t border-[color:var(--landing-border)]" />
                <span className="mx-2 text-sm text-[var(--landing-muted)]">
                  o
                </span>
                <div className="flex-grow border-t border-[color:var(--landing-border)]" />
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
