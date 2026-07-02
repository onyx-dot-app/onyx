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
        title="We'll be back soon."
        description="Our team is performing scheduled maintenance. Please check back in a little while."
      />
    </AuthLayouts.Card>
  );
}
