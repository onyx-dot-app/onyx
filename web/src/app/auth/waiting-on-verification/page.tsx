import { getCurrentUserSS } from "@/lib/users/svcSS";
import { getAuthTypeMetadataSS } from "@/lib/auth/svcSS";
import { AuthTypeMetadata } from "@/lib/auth/types";
import { redirect } from "next/navigation";
import { User } from "@/lib/types";
import { RequestNewVerificationEmail } from "./RequestNewVerificationEmail";
import { Logo } from "@/lib/app/components";
import { Text } from "@opal/components";
import { markdown, richNodes } from "@opal/utils";
import { getTranslations } from "next-intl/server";

export default async function Page() {
  const t = await getTranslations("auth");
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
    return redirect("/auth/login");
  }

  if (!authTypeMetadata?.requiresVerification || currentUser.is_verified) {
    return redirect("/app");
  }

  return (
    <main>
      <div className="min-h-screen flex flex-col items-center justify-center py-12 px-4 sm:px-6 lg:px-8 gap-4">
        <Logo folded size={64} className="mx-auto w-fit" />
        <div className="flex flex-col gap-2">
          <Text as="span">
            {markdown(
              t("waitingOnVerification.greeting.text", {
                email: currentUser.email,
              })
            )}
          </Text>
          <Text as="span">
            {richNodes(
              t.rich("waitingOnVerification.helpPrompt.text", {
                link: (chunks) => (
                  <RequestNewVerificationEmail email={currentUser.email}>
                    {chunks}
                  </RequestNewVerificationEmail>
                ),
              })
            )}
          </Text>
        </div>
      </div>
    </main>
  );
}
