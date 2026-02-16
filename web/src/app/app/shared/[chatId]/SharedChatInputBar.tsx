"use client";

import Button from "@/refresh-components/buttons/Button";
import Text from "@/refresh-components/texts/Text";
import { Button as OpalButton, OpenButton } from "@opal/components";
import { OpenAISVG } from "@/components/icons/icons";
import SvgPlusCircle from "@opal/icons/plus-circle";
import SvgArrowUp from "@opal/icons/arrow-up";
import SvgSliders from "@opal/icons/sliders";
import SvgHourglass from "@opal/icons/hourglass";
import SvgEditBig from "@opal/icons/edit-big";

export default function SharedChatInputBar() {
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
            <OpalButton icon={SvgPlusCircle} prominence="tertiary" disabled />
            <OpalButton icon={SvgSliders} prominence="tertiary" disabled />
            <OpalButton icon={SvgHourglass} variant="select" disabled />
          </div>

          {/* Right side controls */}
          <div className="flex flex-row items-center gap-1">
            <OpenButton icon={OpenAISVG} foldable disabled>
              GPT-4o
            </OpenButton>
            <OpalButton icon={SvgArrowUp} disabled />
          </div>
        </div>
      </div>

      {/* Fade overlay */}
      <div className="absolute inset-0 rounded-16 backdrop-blur-sm bg-background-neutral-00/50" />

      {/* CTA button */}
      <div className="absolute inset-0 flex items-center justify-center">
        <Button secondary leftIcon={SvgEditBig} href="/app">
          Start New Session
        </Button>
      </div>
    </div>
  );
}
