import {
  AuthTypeMetadata,
  getAuthTypeMetadataSS,
  getCurrentUserSS,
} from "@/lib/userSS";
import { redirect } from "next/navigation";
import { HealthCheckBanner } from "@/components/health/healthcheck";
import { User } from "@/lib/types";
import Text from "@/components/ui/text";
import { Logo } from "@/components/logo/Logo";
import { completeTenantSetup } from "@/lib/tenant";

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
    console.log(`Some fetch failed for the waiting-on-setup page - ${e}`);
  }

  if (!currentUser) {
    if (authTypeMetadata?.authType === "disabled") {
      return redirect("/chat");
    }
    return redirect("/auth/login");
  }

  // If the user is already verified, redirect to chat
  if (!authTypeMetadata?.requiresVerification || currentUser.is_verified) {
    // Trigger the tenant setup completion in the background
    if (currentUser.email) {
      try {
        await completeTenantSetup(currentUser.email);
      } catch (e) {
        console.error("Failed to complete tenant setup:", e);
      }
    }
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
              Hey <i>{currentUser.email}</i> - we're setting up your account.
              <br />
              This may take a few moments. You'll be redirected automatically
              when it's ready.
              <br />
              <br />
              If you're not redirected within a minute, please refresh the page.
            </Text>
          </div>
        </div>
      </div>
    </main>
  );
}
