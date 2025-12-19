"use client";
import { SvgActions } from "@opal/icons";
import { AdminPageLayout } from "@/refresh-components/layouts/AdminPageLayout";
import OpenApiPageContent from "@/sections/actions/OpenApiPageContent";
export default function Main() {
  return (
    <AdminPageLayout
      icon={SvgActions}
      title="OpenAPI Actions"
      description="Connect OpenAPI servers to add custom actions and tools for your assistants."
    >
      <OpenApiPageContent />
    </AdminPageLayout>
  );
}
