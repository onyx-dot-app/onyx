"use client";

import { AuthLayouts } from "@opal/layouts";
import { useSettings } from "@/lib/settings/hooks";

export default function MaintenancePage() {
  const { logoUrl, appName } = useSettings();

  return (
    <AuthLayouts.Card
      title="Under Maintenance"
      description={`${appName} is temporarily unavailable.`}
      logoSrc={logoUrl}
    >
      <AuthLayouts.Message
        title="Maintenance in progress."
        description="Onyx is currently under scheduled maintenance. Please check back later. Contact support"
      />
    </AuthLayouts.Card>
  );
}
