import { HoverPopup } from "@/components/HoverPopup";
import SvgPlusCircle from "@/icons/plus-circle";
import IconButton from "@/refresh-components/buttons/IconButton";
import { useState } from "react";

export interface DocumentSelectorProps {
  isSelected: boolean;
  handleSelect: () => void;
  isDisabled?: boolean;
}

export default function DocumentSelector({
  isSelected,
  handleSelect,
  isDisabled,
}: DocumentSelectorProps) {
  const [popupDisabled, setPopupDisabled] = useState(false);

  function onClick(e: React.MouseEvent) {
    e.stopPropagation();
    if (!isDisabled) {
      setPopupDisabled(true);
      handleSelect();
      // re-enable popup after 1 second so that we don't show the popup immediately upon the
      // user de-selecting a document
      setTimeout(() => {
        setPopupDisabled(false);
      }, 1000);
    }
  }

  function Main() {
    return (
      <IconButton
        icon={SvgPlusCircle}
        onClick={onClick}
        active={isSelected}
        disabled={isDisabled}
        tertiary
      />
    );
  }

  if (isDisabled && !popupDisabled) {
    return (
      <div className="ml-auto">
        <HoverPopup
          mainContent={Main()}
          popupContent={
            <div className="w-48">
              LLM context limit reached 😔 If you want to chat with this
              document, please de-select others to free up space.
            </div>
          }
          direction="left-top"
        />
      </div>
    );
  }

  return Main();
}
