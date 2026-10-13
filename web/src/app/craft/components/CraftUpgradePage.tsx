"use client";

import { Button } from "@opal/components";
import { IllustrationContent } from "@opal/layouts";
import SvgNoAccess from "@opal/illustrations/no-access";
import { useUser } from "@/providers/UserProvider";

export default function CraftUpgradePage() {
  const { isAdmin } = useUser();

  return (
    <div className="flex h-screen w-full flex-col items-center justify-center gap-4 p-8">
      <IllustrationContent
        illustration={SvgNoAccess}
        title="Craft requires a Business plan"
        description={
          isAdmin
            ? "Craft is available on the Business and Enterprise plans. It is not supported on the Community Edition until Craft merges into the main chat."
            : "Craft is available on the Business and Enterprise plans. Ask your admin to upgrade to use Craft."
        }
      />
      <div className="flex flex-row gap-2">
        <Button prominence="secondary" href="/app">
          Back to chat
        </Button>
        {isAdmin && <Button href="/admin/billing">View plans</Button>}
      </div>
    </div>
  );
}
