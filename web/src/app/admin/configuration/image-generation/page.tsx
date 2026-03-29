"use client";

import * as SettingsLayouts from "@/layouts/settings-layouts";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import { SvgLock } from "@opal/icons";
import Text from "@/refresh-components/texts/Text";

const route = ADMIN_ROUTES.IMAGE_GENERATION;

export default function Page() {
  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header
        icon={route.icon}
        title={route.title}
        description="Settings for in-chat image generation."
      />
      <SettingsLayouts.Body>
        <div className="relative">
          {/* Coming Soon overlay */}
          <div className="absolute inset-0 z-10 flex flex-col items-center justify-center bg-background-tint-00/80 backdrop-blur-sm rounded-16">
            <div className="flex flex-col items-center gap-3">
              <div className="flex items-center justify-center w-14 h-14 rounded-full bg-background-neutral-02 border border-border-01">
                <SvgLock className="w-7 h-7 text-text-03" />
              </div>
              <Text headingH3 text04>
                Coming Soon
              </Text>
              <Text secondaryBody text03 className="text-center max-w-xs">
                Image generation will be available in a future update.
              </Text>
            </div>
          </div>

          {/* Blurred content underneath */}
          <div className="pointer-events-none select-none opacity-30 blur-[1px]">
            <div className="flex flex-col gap-6">
              <div className="flex flex-col gap-0.5">
                <Text mainContentEmphasis text05>
                  Image Generation Model
                </Text>
                <Text secondaryBody text03>
                  Select a model to generate images in chat.
                </Text>
              </div>
              <div className="flex flex-col gap-2 p-4 rounded-12 border border-border-01 bg-background-tint-00 h-48" />
              <div className="flex flex-col gap-2 p-4 rounded-12 border border-border-01 bg-background-tint-00 h-32" />
            </div>
          </div>
        </div>
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
