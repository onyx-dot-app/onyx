"use client";
import { HealthCheckBanner } from "../health/healthcheck";
import { Separator } from "@/components/ui/separator";

export function AdminPageTitle({
  icon,
  title,
  farRightElement,
  includeDivider = true,
}: {
  icon: JSX.Element;
  title: string | JSX.Element;
  farRightElement?: JSX.Element;
  includeDivider?: boolean;
}) {
  return (
    <div className="w-full">
      <div className="mb-4">
        <HealthCheckBanner />
      </div>
      <div className="w-full flex">
        <h1 className="text-3xl text-text-900 font-bold flex gap-x-2">
          {icon} {title}
        </h1>
        {farRightElement && <div className="ml-auto">{farRightElement}</div>}
      </div>
      {includeDivider ? <Separator /> : <div className="mb-6" />}
    </div>
  );
}
