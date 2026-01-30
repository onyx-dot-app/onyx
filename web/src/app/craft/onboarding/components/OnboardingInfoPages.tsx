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
      <Text mainContentBody text04 className="text-center">
        While we sync your data, try our demo dataset
        <br />
        of 1,000+ simulated documents!
      </Text>
      <img
        src="/craft_demo_image_2.png"
        alt="Onyx Craft"
        className="max-w-full h-auto rounded-12"
      />
      <Text mainContentBody text04 className="text-center">
        In the simulated dataset, you are {article}{" "}
        <span className="font-semibold">{positionText}</span> named{" "}
        <span className="font-semibold">
          {personaInfo?.name || "Temp temp"}
        </span>{" "}
        working at <span className="font-semibold">{DEMO_COMPANY_NAME}</span>
      </Text>
      <div className="flex items-center justify-center gap-4">
        <SimpleTooltip tooltip="Google Drive">
          <span className="inline-flex items-center cursor-help">
            <GoogleDriveIcon size={25} />
          </span>
        </SimpleTooltip>
        <SimpleTooltip tooltip="GitHub">
          <span className="inline-flex items-center cursor-help">
            <GithubIcon size={25} />
          </span>
        </SimpleTooltip>
        <SimpleTooltip tooltip="HubSpot">
          <span className="inline-flex items-center cursor-help">
            <HubSpotIcon size={25} />
          </span>
        </SimpleTooltip>
        <SimpleTooltip tooltip="Linear">
          <span className="inline-flex items-center cursor-help">
            <LinearIcon size={25} />
          </span>
        </SimpleTooltip>
        <SimpleTooltip tooltip="Fireflies">
          <span className="inline-flex items-center cursor-help">
            <FirefliesIcon size={25} />
          </span>
        </SimpleTooltip>
        <SimpleTooltip tooltip="Gmail">
          <span className="inline-flex items-center cursor-help">
            <GmailIcon size={25} />
          </span>
        </SimpleTooltip>
        <SimpleTooltip tooltip="Slack">
          <span className="inline-flex items-center cursor-help">
            <ColorSlackIcon size={25} />
          </span>
        </SimpleTooltip>
      </div>
    </div>
  );
}
