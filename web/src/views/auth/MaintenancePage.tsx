"use client";

import { AuthLayouts } from "@opal/layouts";
import { useSettings } from "@/lib/settings/hooks";
import { markdown } from "@opal/utils";
import { welcomeCardCopy } from "@/views/auth/strings";

export default function MaintenancePage() {
  const { logoUrl, appName } = useSettings();

  return (
    <AuthLayouts.Card {...welcomeCardCopy(appName)} logoSrc={logoUrl}>
      <AuthLayouts.Message
        title="Maintenance in progress."
        description={markdown(
          "Onyx is currently under scheduled maintenance. Please check back later. [Contact support](mailto:support@onyx.app)"
        )}
      />
    </AuthLayouts.Card>
  );
}
