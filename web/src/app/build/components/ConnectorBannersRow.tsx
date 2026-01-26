"use client";

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
import { SvgChevronRight, SvgCalendar } from "@opal/icons";
import { useBuildConnectors } from "@/app/build/hooks/useBuildConnectors";
import { ONYX_CRAFT_CALENDAR_URL } from "@/app/build/v1/constants";

interface ConnectorBannersRowProps {
  className?: string;
}

function IconWrapper({ children }: { children: React.ReactNode }) {
  return (
    <div className="w-6 h-6 rounded-full bg-background-neutral-00 border border-border-01 flex items-center justify-center overflow-hidden">
      {children}
    </div>
  );
}

/**
 * Row of two banners that appear above the InputBar after first assistant response.
 * - Left: "Connect your data" - exact same look as welcome page banner, but flipped
 * - Right: "Get help setting up connectors" - links to cal.com booking
 *
 * Only shows if user has no connectors configured.
 * Slides up from the input bar with animation.
 */
export default function ConnectorBannersRow({
  className,
}: ConnectorBannersRowProps) {
  const { hasConnectorEverSucceeded } = useBuildConnectors();

  // Hide if user has successfully synced at least one connector
  if (hasConnectorEverSucceeded) {
    return null;
  }

  const handleConnectClick = () => {
    window.location.href = "/build/v1/configure";
  };

  const handleHelpClick = () => {
    window.open(ONYX_CRAFT_CALENDAR_URL, "_blank");
  };

  return (
    <div
      className={cn(
        "flex justify-center animate-in slide-in-from-bottom-2 fade-in duration-300",
        className
      )}
    >
      {/* Left banner: Connect your data - exact same as welcome page but flipped */}
      <button
        onClick={handleConnectClick}
        className={cn(
          // Layout
          "flex items-center justify-between gap-2",
          "px-4 py-2",
          // Sizing - thin and slightly narrower than 50% width
          "h-9 w-[calc(48%-4px)]",
          // Appearance - rounded top left only
          "bg-background-neutral-01 hover:bg-background-neutral-02",
          "rounded-tl-12 rounded-tr-none rounded-bl-none rounded-br-none",
          // Border - flipped: no bottom border instead of no top
          "border border-b-0 border-border-01",
          // Transition
          "transition-colors duration-200",
          // Cursor
          "cursor-pointer",
          // Group for hover effects
          "group"
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

      {/* Right banner: Get help setting up connectors */}
      <button
        onClick={handleHelpClick}
        className={cn(
          // Layout
          "flex items-center justify-center gap-2",
          "px-4 py-2",
          // Sizing - same as left banner
          "h-9 w-[calc(49%)]",
          // Appearance - rounded top right only
          "bg-background-neutral-01 hover:bg-background-neutral-02",
          "rounded-tr-12 rounded-tl-none rounded-bl-none rounded-br-none",
          // Border - flipped: no bottom border
          "border border-b-0 border-border-01",
          // Transition
          "transition-colors duration-200",
          // Cursor
          "cursor-pointer"
        )}
      >
        {/* Calendar icon */}
        <SvgCalendar className="h-4 w-4 text-text-03" />

        {/* Text */}
        <Text secondaryBody text03>
          Get help setting up connectors
        </Text>

        {/* Arrow indicator */}
        <SvgChevronRight className="h-4 w-4 text-text-03" />
      </button>
    </div>
  );
}
