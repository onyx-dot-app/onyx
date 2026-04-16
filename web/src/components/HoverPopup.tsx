import { JSX } from "react";
import { Tooltip } from "@opal/components";

interface HoverPopupProps {
  mainContent: string | JSX.Element;
  popupContent: string | JSX.Element;
  classNameModifications?: string;
  direction?: "left" | "left-top" | "bottom" | "top";
  style?: "basic" | "dark";
}

export const HoverPopup = ({
  mainContent,
  popupContent,
  direction = "bottom",
}: HoverPopupProps) => {
  return (
    <Tooltip
      tooltip={popupContent}
      side={direction === "left-top" ? "left" : direction}
    >
      <div>{mainContent}</div>
    </Tooltip>
  );
};
