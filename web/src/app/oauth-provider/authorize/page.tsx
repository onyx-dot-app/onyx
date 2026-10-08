import { notFound, redirect } from "next/navigation";
import { loginPath } from "@/lib/auth/paths";
import { getCurrentUserSS } from "@/lib/users/svcSS";
import OAuthProviderConsent from "@/sections/oauth-provider/OAuthProviderConsent";

interface OAuthProviderAuthorizePageProps {
  searchParams: Promise<{ request?: string | string[] }>;
}

const REQUEST_ID_PATTERN = /^[A-Za-z0-9_-]{43}$/;

export default async function OAuthProviderAuthorizePage({
  searchParams,
}: OAuthProviderAuthorizePageProps) {
  const requestId = (await searchParams).request;
  if (typeof requestId !== "string" || !REQUEST_ID_PATTERN.test(requestId)) {
    notFound();
  }

  const user = await getCurrentUserSS();
  if (!user) {
    redirect(
      loginPath({
        next: `/oauth-provider/authorize?request=${requestId}`,
      })
    );
  }

  return <OAuthProviderConsent requestId={requestId} userId={user.id} />;
}
