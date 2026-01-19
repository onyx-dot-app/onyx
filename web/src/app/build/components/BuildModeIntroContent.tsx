"use client";

import { motion } from "motion/react";
import { OnyxLogoTypeIcon } from "@/components/icons/icons";
import Text from "@/refresh-components/texts/Text";

interface BuildModeIntroContentProps {
  onClose: () => void;
  onTryBuildMode: () => void;
}

export default function BuildModeIntroContent({
  onClose,
  onTryBuildMode,
}: BuildModeIntroContentProps) {
  return (
    <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none gap-6">
      <motion.div
        initial={{ opacity: 0, scale: 0.8 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{ duration: 0.8, delay: 0.5 }}
      >
        <OnyxLogoTypeIcon size={200} className="text-white" />
      </motion.div>
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.8, delay: 0.8 }}
      >
        <Text headingH1 inverted className="!text-8xl">
          Build Mode
        </Text>
      </motion.div>
      <motion.div
        className="flex gap-4 pointer-events-auto"
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.8, delay: 1.1 }}
      >
        <button
          className="px-6 py-3 border border-white text-white font-semibold rounded-lg hover:bg-white/10 transition-colors"
          onClick={(e) => {
            e.stopPropagation();
            onClose();
          }}
        >
          Return to Chat
        </button>
        <button
          className="px-6 py-3 bg-white text-black font-semibold rounded-lg hover:bg-gray-200 transition-colors"
          onClick={(e) => {
            e.stopPropagation();
            onTryBuildMode();
          }}
        >
          Try Build Mode
        </button>
      </motion.div>
    </div>
  );
}
