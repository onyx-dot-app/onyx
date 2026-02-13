"use client";

import Text from "@/refresh-components/texts/Text";
import SimpleTooltip from "@/refresh-components/SimpleTooltip";
import {
  WorkArea,
  Level,
  getPersonaInfo,
  getPositionText,
  DEMO_COMPANY_NAME,
} from "@/app/craft/onboarding/constants";
import {
  GoogleDriveIcon,
  GithubIcon,
  HubSpotIcon,
  LinearIcon,
  FirefliesIcon,
  GmailIcon,
  ColorSlackIcon,
} from "@/components/icons/icons";

interface OnboardingInfoPagesProps {
  step: "page1" | "page2";
  workArea: WorkArea | undefined;
  level: Level | undefined;
}

export default function OnboardingInfoPages({
  step,
  workArea,
  level,
}: OnboardingInfoPagesProps) {
  // Get persona info from mapping (only if both are valid enum values)
  const personaInfo =
    workArea && level ? getPersonaInfo(workArea, level) : undefined;

  // Helper function to determine article (a/an) based on first letter
  const getArticle = (word: string | undefined): string => {
    if (!word || word.length === 0) return "a";
    const firstLetter = word.toLowerCase()[0];
    if (!firstLetter) return "a";
    const vowels = ["a", "e", "i", "o", "u"];
    return vowels.includes(firstLetter) ? "an" : "a";
  };

  // Get position text using shared helper (only if workArea is valid enum)
  const positionText = workArea ? getPositionText(workArea, level) : "Not set";

  // Determine article based on position text
  const article = getArticle(positionText);

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
