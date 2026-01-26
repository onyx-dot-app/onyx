"use client";

import { useRouter } from "next/navigation";
import { cn } from "@/lib/utils";
import Text from "@/refresh-components/texts/Text";
import {
  ConfluenceIcon,
  GoogleDriveIcon,
  GithubIcon,
  NotionIcon,
  ColorSlackIcon,
  HubSpotIcon,
} from "@/components/icons/icons";
import { SvgChevronRight } from "@opal/icons";
import { useBuildConnectors } from "@/app/build/hooks/useBuildConnectors";

interface ConnectDataBannerProps {
  className?: string;
}

function IconWrapper({ children }: { children: React.ReactNode }) {
  return (
    <div className="w-6 h-6 rounded-full bg-background-neutral-00 border border-border-01 flex items-center justify-center overflow-hidden">
      {children}
    </div>
  );
}

export default function ConnectDataBanner({
  className,
}: ConnectDataBannerProps) {
  const router = useRouter();
  const { hasConnectorEverSucceeded, isLoading } = useBuildConnectors();

  const handleClick = () => {
    router.push("/build/v1/configure");
  };

  // Only show banner if user hasn't successfully synced any connectors (and not loading)
  if (isLoading || hasConnectorEverSucceeded) {
    return null;
  }

  return (
    <div className="relative">
      <button
        onClick={handleClick}
        className={cn(
          // Layout
          "flex items-center justify-between gap-2",
          "mx-auto px-4 py-2",
          // Sizing - thin and full width to match InputBar
          "h-9 w-[50%]",
          // Appearance - slightly different color, rounded bottom
          "bg-background-neutral-01 hover:bg-background-neutral-02",
          "rounded-b-12 rounded-t-none",
          // Border for definition
          "border border-t-0 border-border-01",
          // Transition
          "transition-colors duration-200",
          // Cursor
          "cursor-pointer",
          // Group for hover effects
          "group",
          className
        )}
      >
        {/* Left side: 3 icons */}
        <div className="flex items-center -space-x-2">
          {/* Outermost - no movement */}
          <div>
            <IconWrapper>
              <ColorSlackIcon size={16} />
            </IconWrapper>
          </div>
          {/* Middle - slight movement */}
          <div className="transition-transform duration-200 group-hover:translate-x-2">
            <IconWrapper>
              <GoogleDriveIcon size={16} />
            </IconWrapper>
          </div>
          {/* Innermost - moves towards center */}
          <div className="transition-transform duration-200 group-hover:translate-x-4">
            <IconWrapper>
              <ConfluenceIcon size={16} />
            </IconWrapper>
          </div>
        </div>

        {/* Center: Text and Arrow */}
        <div className="flex items-center justify-center gap-1">
          <Text secondaryBody text03>
            Connect your data
          </Text>
          <SvgChevronRight className="h-4 w-4 text-text-03" />
        </div>

        {/* Right side: 3 icons */}
        <div className="flex items-center -space-x-2">
          {/* Innermost - moves towards center */}
          <div className="transition-transform duration-200 group-hover:-translate-x-4">
            <IconWrapper>
              <GithubIcon size={16} />
            </IconWrapper>
          </div>
          {/* Middle - slight movement */}
          <div className="transition-transform duration-200 group-hover:-translate-x-2">
            <IconWrapper>
              <NotionIcon size={16} />
            </IconWrapper>
          </div>
          {/* Outermost - no movement */}
          <div>
            <IconWrapper>
              <HubSpotIcon size={16} />
            </IconWrapper>
          </div>
        </div>
      </button>
    </div>
  );
}
