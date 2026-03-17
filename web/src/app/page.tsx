import type { Route } from "next";
import { redirect } from "next/navigation";

import Landing from "@/app/Landing";
import { getAuthTypeMetadataSS, getCurrentUserSS } from "@/lib/userSS";

const APP_ROUTE: Route = "/app";
const WAITING_ON_VERIFICATION_ROUTE: Route = "/auth/waiting-on-verification";

export default async function Page() {
  try {
    const [authTypeMetadata, currentUser] = await Promise.all([
      getAuthTypeMetadataSS(),
      getCurrentUserSS(),
    ]);

    if (
      currentUser?.is_active &&
      !currentUser.is_anonymous_user &&
      authTypeMetadata?.requiresVerification &&
      !currentUser.is_verified
    ) {
      redirect(WAITING_ON_VERIFICATION_ROUTE);
    }

    if (currentUser?.is_active && !currentUser.is_anonymous_user) {
      redirect(APP_ROUTE);
    }
  } catch (e) {
    console.log(`Some fetch failed for the landing page - ${e}`);
  }

  return <Landing />;
}
