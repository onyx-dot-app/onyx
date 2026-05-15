"use client";

import Text from "@/refresh-components/texts/Text";

interface OnboardingInfoPagesProps {
  step: "page1" | "page2";
}

export default function OnboardingInfoPages({
  step,
}: OnboardingInfoPagesProps) {
  if (step === "page1") {
    return (
      <div className="flex-1 flex flex-col gap-6 items-center justify-center">
        <Text headingH2 text05>
          What is Onyx Craft?
        </Text>
        <img
          src="/craft_demo_image_1.png"
          alt="Onyx Craft"
          className="max-w-full h-auto rounded-12"
        />
        <Text mainContentBody text04 className="text-center">
          Beautiful dashboards, slides, and reports.
          <br />
          Built by AI agents that know your world. Privately and securely.
        </Text>
      </div>
    );
  }

  // Page 2
  return (
    <div className="flex-1 flex flex-col gap-6 items-center justify-center">
      <Text headingH2 text05>
        Let's get started!
      </Text>
      <img
        src="/craft_demo_image_2.png"
        alt="Onyx Craft"
        className="max-w-full h-auto rounded-12"
      />
    </div>
  );
}
