"use client";

import { cn } from "@opal/utils";
import Text from "@/refresh-components/texts/Text";
import {
  SvgConfluence,
  SvgGithub,
  SvgGoogleDrive,
  SvgHubspot,
  SvgNotion,
  SvgSlack,
} from "@opal/logos";
import { SvgChevronRight } from "@opal/icons";
import useCCPairs from "@/hooks/useCCPairs";
import { useUser } from "@/providers/UserProvider";

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
  const { isAdmin, isCurator } = useUser();
  const canManageConnectors = isAdmin || isCurator;
  const { ccPairs, isLoading } = useCCPairs(canManageConnectors);
  const hasConnectorEverSucceeded = ccPairs.some((cc) => cc.has_successful_run);

  if (!canManageConnectors || isLoading || hasConnectorEverSucceeded) {
    return null;
  }

  const handleClick = () => {
    window.location.href = "/admin/indexing/status";
  };

  return (
    <div className="relative">
      <button
        onClick={handleClick}
        className={cn(
          "flex items-center justify-between gap-2",
          "mx-auto px-4 py-2",
          "h-9 w-[50%]",
          "bg-background-neutral-01 hover:bg-background-neutral-02",
          "rounded-b-12 rounded-t-none",
          "border border-t-0 border-border-01",
          "transition-colors duration-200",
          "cursor-pointer",
          "group",
          className
        )}
      >
        <div className="flex items-center -space-x-2">
          <div>
            <IconWrapper>
              <SvgSlack size={16} />
            </IconWrapper>
          </div>
          <div className="transition-transform duration-200 group-hover:translate-x-2">
            <IconWrapper>
              <SvgGoogleDrive size={16} />
            </IconWrapper>
          </div>
          <div className="transition-transform duration-200 group-hover:translate-x-4">
            <IconWrapper>
              <SvgConfluence size={16} />
            </IconWrapper>
          </div>
        </div>

        <div className="flex items-center justify-center gap-1">
          <Text secondaryBody text03>
            Connect your data
          </Text>
          <SvgChevronRight className="h-4 w-4 text-text-03" />
        </div>

        <div className="flex items-center -space-x-2">
          <div className="transition-transform duration-200 group-hover:-translate-x-4">
            <IconWrapper>
              <SvgGithub size={16} />
            </IconWrapper>
          </div>
          <div className="transition-transform duration-200 group-hover:-translate-x-2">
            <IconWrapper>
              <SvgNotion size={16} />
            </IconWrapper>
          </div>
          <div>
            <IconWrapper>
              <SvgHubspot size={16} />
            </IconWrapper>
          </div>
        </div>
      </button>
    </div>
  );
}
