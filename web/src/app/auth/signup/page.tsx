import { HealthCheckBanner } from "@/components/health/healthcheck";
import { User } from "@/lib/types";
import {
  getCurrentUserSS,
  getAuthTypeMetadataSS,
  AuthTypeMetadata,
} from "@/lib/userSS";
import { redirect } from "next/navigation";
import { EmailPasswordForm } from "../login/EmailPasswordForm";
import { Card, Title, Text } from "@tremor/react";
import Link from "next/link";
import { fetchEEASettings } from "@/lib/eea/fetchEEASettings";
import { Logo } from "@/components/Logo";
import Image from "next/image";

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
  const config = await fetchEEASettings();
  


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

  // only enable this page if basic login is enabled
  if (authTypeMetadata?.authType !== "basic") {
    return redirect("/");
  }

  return (
    <main>
      <div className="absolute top-10x w-full">
        <HealthCheckBanner />
      </div>
      <div className="min-h-screen-full flex items-center justify-center py-12 px-4 sm:px-6 lg:px-8">
        <div>
          <div className="h-16 w-[92px] mx-auto">
            <Image
              src="/EEA_logo_compact_EN.svg"
              alt="Logo"
              width="1419"
              height="1520"
            />
          </div>
          <Card className="mt-4 w-96">
            <div className="flex">
              <Title className="mb-2 mx-auto font-bold">
                Sign Up for GPT Lab
              </Title>
            </div>
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
          </Card>
        </div>
      </div>

    </main>
  );
};

export default Page;
