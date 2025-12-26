"use client";

import { SvgActions } from "@opal/icons";
import { AdminPageTitle } from "@/components/admin/Title";
import OpenApiPageContent from "@/sections/actions/OpenApiPageContent";
import Text from "@/refresh-components/texts/Text";

export default function Main() {
  return (
    <div className="container">
      <AdminPageTitle icon={SvgActions} title="OpenAPI Actions" />
      <Text secondaryBody text03 className="pt-4 pb-6">
        Connect OpenAPI servers to add custom actions and tools for your
        assistants.
      </Text>
      <OpenApiPageContent />
    </div>
  );
}
