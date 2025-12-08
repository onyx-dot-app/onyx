"use client";
import SvgServer from "@/icons/server";
import PageHeader from "@/refresh-components/headers/PageHeader";
import OpenApiPageContent from "@/sections/actions/OpenApiPageContent";
export default function Main() {
  return (
    <div className="mx-auto container">
      <PageHeader
        icon={SvgServer}
        title="OpenAPI Actions"
        description="Connect OpenAPI servers to add custom actions and tools for your assistants."
      />

      <OpenApiPageContent />
    </div>
  );
}
