import {
  AuthTypeMetadata,
  getAuthTypeMetadataSS,
  getCurrentUserSS,
} from "@/lib/userSS";
import { redirect } from "next/navigation";
import { HealthCheckBanner } from "@/components/health/healthcheck";
import { User } from "@/lib/types";
import Text from "@/components/ui/text";
import { RequestNewVerificationEmail } from "./RequestNewVerificationEmail";
import { Logo } from "@/components/logo/Logo";

export default async function Page() {
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

  if (!currentUser) {
    if (authTypeMetadata?.authType === "disabled") {
      return redirect("/chat");
    }
    return redirect("/auth/login");
  }

  if (!authTypeMetadata?.requiresVerification || currentUser.is_verified) {
    return redirect("/chat");
  }

  return (
    <main>
      <div className="absolute top-10x w-full">
        <HealthCheckBanner />
      </div>
      <div className="min-h-screen flex items-center justify-center py-12 px-4 sm:px-6 lg:px-8">
        <div>
          <Logo height={64} width={64} className="mx-auto w-fit" />

          <div className="flex">
            <Text className="text-center font-medium text-lg mt-6 w-108">
              Hey <i>{currentUser.email}</i> - it looks like you haven&apos;t
              verified your email yet.
              <br />
              Check your inbox for an email from us to get started!
              <br />
              <br />
              If you don&apos;t see anything, click{" "}
              <RequestNewVerificationEmail email={currentUser.email}>
                here
              </RequestNewVerificationEmail>{" "}
              to request a new email.
            </Text>
          </div>
        </div>
      </div>
    </main>
  );
}
