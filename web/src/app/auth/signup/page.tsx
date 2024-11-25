import { HealthCheckBanner } from "@/components/health/healthcheck";
import { User } from "@/lib/types";
import {
  getCurrentUserSS,
  getAuthTypeMetadataSS,
  AuthTypeMetadata,
  getAuthUrlSS,
} from "@/lib/userSS";
import { redirect } from "next/navigation";
import { EmailPasswordForm } from "../login/EmailPasswordForm";
import Text from "@/components/ui/text";
import Link from "next/link";
import Image from "next/image";
import { SignInButton } from "../login/SignInButton";
import AuthFlowContainer from "@/components/auth/AuthFlowContainer";

const Page = async () => {
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
    return redirect("/");
  }

  // if user is already logged in, take them to the main app page
  if (currentUser && currentUser.is_active) {
    if (!authTypeMetadata?.requiresVerification || currentUser.is_verified) {
      return redirect("/");
    }
    return redirect("/auth/waiting-on-verification");
  }
  const cloud = authTypeMetadata?.authType === "cloud";

  // only enable this page if basic login is enabled
  if (authTypeMetadata?.authType !== "basic" && !cloud) {
    return redirect("/");
  }

  let authUrl: string | null = null;
  if (cloud && authTypeMetadata) {
    authUrl = await getAuthUrlSS(authTypeMetadata.authType, null);
  }

  return (
    <AuthFlowContainer>
      <HealthCheckBanner />

      <>
        <div className="absolute top-10x w-full"></div>
        <div className="flex w-full flex-col justify-center">
          <h2 className="text-center text-xl text-strong font-bold">
            {cloud ? "Complete your sign up" : "Sign Up for Danswer"}
          </h2>

          {cloud && authUrl && (
            <div className="w-full justify-center">
              <SignInButton authorizeUrl={authUrl} authType="cloud" />
              <div className="flex items-center w-full my-4">
                <div className="flex-grow border-t border-background-300"></div>
                <span className="px-4 text-gray-500">or</span>
                <div className="flex-grow border-t border-background-300"></div>
              </div>
            </div>
          )}

          <EmailPasswordForm
            isSignup
            shouldVerify={authTypeMetadata?.requiresVerification}
          />

          <div className="flex">
            <Text className="mt-4 mx-auto">
              Already have an account?{" "}
              <Link href="/auth/login" className="text-link font-medium">
                Log In
              </Link>
            </Text>
          </div>
        </div>
      </>
    </AuthFlowContainer>
  );
};

export default Page;
