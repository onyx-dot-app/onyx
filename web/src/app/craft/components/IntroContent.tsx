"use client";

import { motion } from "motion/react";
import { OnyxLogoTypeIcon } from "@/components/icons/icons";
import Text from "@/refresh-components/texts/Text";
import BigButton from "@/app/craft/components/BigButton";

interface BuildModeIntroContentProps {
  onClose: () => void;
  onTryBuildMode: () => void;
}

export default function BuildModeIntroContent({
  onClose,
  onTryBuildMode,
}: BuildModeIntroContentProps) {
  return (
    <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
      <div className="flex flex-col items-center gap-7 w-full">
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.8, delay: 0.5 }}
          className="w-full relative"
        >
          <div className="grid grid-cols-[1fr_auto_1fr] items-end">
            <div className="flex justify-end">
              <OnyxLogoTypeIcon size={385} className="text-white" />
            </div>
            <div className="w-8"></div>
            <div className="flex justify-start">
              <div
                className="relative inline-flex overflow-visible"
                style={{ transform: "translateX(-0.6em)" }}
              >
                <span className="relative inline-block leading-[3.5]">
                  <Text
                    headingH1
                    className="!text-9xl !text-white relative inline-block"
                    style={{
                      fontFamily: "var(--font-kh-teka)",
                      fontWeight: 500,
                    }}
                  >
                    Craft
                  </Text>
                </span>
                <span
                  className="pointer-events-none absolute top-3 -right-14 text-[1em] uppercase tracking-[0.2em] !text-white"
                  style={{ fontFamily: "var(--font-kh-teka)", fontWeight: 500 }}
                >
                  BETA
                </span>
              </div>
            </div>
          </div>
        </motion.div>
        <motion.div
          className="flex gap-5 pointer-events-auto justify-center"
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.8, delay: 1.3 }}
        >
          <BigButton
            secondary
            className="!border-white !text-white hover:!bg-white/10 active:!bg-white/20 !w-[160px]"
            onClick={(e) => {
              e.stopPropagation();
              onClose();
            }}
          >
            Return Home
          </BigButton>
          <BigButton
            primary
            className="!bg-white !text-black hover:!bg-gray-200 active:!bg-gray-300 !w-[160px]"
            onClick={(e) => {
              e.stopPropagation();
              onTryBuildMode();
            }}
          >
            Start Crafting
          </BigButton>
        </motion.div>
      </div>
    </div>
  );
}
