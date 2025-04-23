interface HoverPopupProps {
  mainContent: string | JSX.Element;
  popupContent: string | JSX.Element;
  classNameModifications?: string;
  direction?: "left" | "left-top" | "bottom" | "top";
  style?: "basic" | "dark";
}

import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";

export const HoverPopup = ({
  mainContent,
  popupContent,
  classNameModifications,
  direction = "bottom",
}: HoverPopupProps) => {
  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>
          <div>{mainContent}</div>
        </TooltipTrigger>
        <TooltipContent
          side={direction === "left-top" ? "left" : direction}
          className={classNameModifications}
        >
          {popupContent}
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
};
