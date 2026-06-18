"use client";

import { Text } from "@opal/components";

interface OnboardingInfoPagesProps {
  step: "page1" | "page2";
}

export default function OnboardingInfoPages({
  step,
}: OnboardingInfoPagesProps) {
  if (step === "page1") {
    return (
      <div className="flex-1 flex flex-col gap-6 items-center justify-center text-center">
        <Text font="heading-h2" color="text-05">
          What is Onyx Craft?
        </Text>
        <img
          src="/craft_demo_image_1.png"
          alt="Onyx Craft"
          className="max-w-full h-auto rounded-12"
        />
        <div className="flex flex-col items-center">
          <Text font="main-content-body" color="text-04">
            Beautiful dashboards, slides, and reports.
          </Text>
          <Text font="main-content-body" color="text-04">
            Built by AI agents that know your world. Privately and securely.
          </Text>
        </div>
      </div>
    );
  }

  // Page 2
  return (
    <div className="flex-1 flex flex-col gap-6 items-center justify-center">
      <Text font="heading-h2" color="text-05">
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
