"use client";

import Text from "@/refresh-components/texts/Text";
import { Button, OpenButton } from "@opal/components";
import { OpenAISVG } from "@/components/icons/icons";
import {
  SvgPlusCircle,
  SvgArrowUp,
  SvgSliders,
  SvgHourglass,
  SvgEditBig,
} from "@opal/icons";

export default function SharedAppInputBar() {
  return (
    <div className="relative w-full">
      <div className="w-full flex flex-col shadow-01 bg-background-neutral-00 rounded-16">
        {/* Textarea area */}
        <div className="flex flex-row items-center w-full">
          <Text text03 className="w-full px-3 pt-3 pb-2 select-none">
            How can Onyx help you today
          </Text>
        </div>

        {/* Bottom toolbar */}
        <div className="flex justify-between items-center w-full p-1 min-h-[40px]">
          {/* Left side controls */}
          <div className="flex flex-row items-center">
            <Button icon={SvgPlusCircle} prominence="tertiary" disabled />
            <Button icon={SvgSliders} prominence="tertiary" disabled />
            <Button icon={SvgHourglass} variant="select" disabled />
          </div>

          {/* Right side controls */}
          <div className="flex flex-row items-center gap-1">
            <OpenButton icon={OpenAISVG} foldable disabled>
              GPT-4o
            </OpenButton>
            <Button icon={SvgArrowUp} disabled />
          </div>
        </div>
      </div>

      {/* Fade overlay */}
      <div className="absolute inset-0 rounded-16 backdrop-blur-sm bg-background-neutral-00/50" />

      {/* CTA button */}
      <div className="absolute inset-0 flex items-center justify-center">
        <Button prominence="secondary" icon={SvgEditBig} href="/app">
          Start New Session
        </Button>
      </div>
    </div>
  );
}
