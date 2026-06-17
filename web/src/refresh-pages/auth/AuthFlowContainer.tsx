"use client";

import type { RichStr } from "@opal/types";
import { useSettings } from "@/lib/settings/hooks";
import { Card } from "@opal/components";
import { Content } from "@opal/layouts";
import { Text } from "@opal/components";
import { SvgOnyxLogo } from "@opal/logos";

interface AuthFlowContainerProps {
  title: string;
  description: string;
  children?: React.ReactNode;
  bottomPrompt?: string | RichStr;
}

export default function AuthFlowContainer({
  title,
  description,
  children,
  bottomPrompt,
}: AuthFlowContainerProps) {
  const { logoUrl } = useSettings();

  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-background p-4">
      <div className="w-full max-w-md">
        <Card padding="lg" rounding="lg">
          {/* 2px = 0.125rem padding around the logo */}
          <div className="p-[0.125rem]">
            {logoUrl ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                alt="Logo"
                src={logoUrl}
                className="rounded-full object-cover object-center"
                style={{ width: "3rem", height: "3rem" }}
              />
            ) : (
              <SvgOnyxLogo size={48} />
            )}
          </div>

          {/* Content 12px = 0.75rem below the logo */}
          <div className="mt-[0.75rem]">
            <Content
              sizePreset="headline"
              variant="heading"
              title={title}
              description={description}
            />
          </div>

          {/* 24px = 1.5rem between header and children */}
          {children !== undefined && (
            <div className="mt-[1.5rem]">{children}</div>
          )}
        </Card>

        {bottomPrompt !== undefined && (
          <div className="mt-[1.5rem] text-center">
            <Text font="main-ui-body" color="text-03">
              {bottomPrompt}
            </Text>
          </div>
        )}
      </div>
    </div>
  );
}
