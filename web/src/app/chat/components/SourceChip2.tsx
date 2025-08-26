import {
  Tooltip,
  TooltipProvider,
  TooltipTrigger,
  TooltipContent,
} from "@/components/ui/tooltip";
import { truncateString } from "@/lib/utils";
import { XIcon } from "lucide-react";
import { useEffect, useState } from "react";

export const SourceChip2 = ({
  icon,
  title,
  onRemove,
  onClick,
  includeTooltip,
  includeAnimation,
  truncateTitle = true,
}: {
  icon?: React.ReactNode;
  title: string;
  onRemove?: () => void;
  onClick?: () => void;
  truncateTitle?: boolean;
  includeTooltip?: boolean;
  includeAnimation?: boolean;
}) => {
  const [isNew, setIsNew] = useState(true);
  const [isTooltipOpen, setIsTooltipOpen] = useState(false);

  useEffect(() => {
    const timer = setTimeout(() => setIsNew(false), 300);
    return () => clearTimeout(timer);
  }, []);

  return (
    <TooltipProvider>
      <Tooltip
        delayDuration={0}
        open={isTooltipOpen}
        onOpenChange={setIsTooltipOpen}
      >
        <TooltipTrigger
          onMouseEnter={() => setIsTooltipOpen(true)}
          onMouseLeave={() => setIsTooltipOpen(false)}
        >
          <div
            onClick={onClick ? onClick : undefined}
            className={`
              h-6
              px-2
              bg-background-dark
              text-text-800
              hover:bg-background-800
              hover:text-text-100
              rounded-2xl
              justify-center
              items-center
              inline-flex
              transition-colors
              duration-200
              ${includeAnimation && isNew ? "animate-fade-in-scale" : ""}
              ${onClick ? "cursor-pointer" : ""}
            `}
          >
            {icon && (
              <div className="w-[17px] h-4 p-[3px] flex-col justify-center items-center gap-2.5 inline-flex">
                <div className="h-2.5 relative">{icon}</div>
              </div>
            )}
            <div className="text-xs font-medium leading-normal">
              {truncateTitle ? truncateString(title, 50) : title}
            </div>
            {onRemove && (
              <XIcon
                size={12}
                className="ml-2 cursor-pointer"
                onClick={(e: React.MouseEvent<SVGSVGElement>) => {
                  e.stopPropagation();
                  onRemove();
                }}
              />
            )}
          </div>
        </TooltipTrigger>
        {includeTooltip && title.length > 50 && (
          <TooltipContent
            className="!pointer-events-none z-[2000000]"
            onMouseEnter={() => setIsTooltipOpen(false)}
          >
            <p>{title}</p>
          </TooltipContent>
        )}
      </Tooltip>
    </TooltipProvider>
  );
};
