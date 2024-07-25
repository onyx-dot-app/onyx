import { HoverPopup } from "@/components/HoverPopup";
import { useState } from "react";

export function DocumentSelector({
  isSelected,
  handleSelect,
  isDisabled,
}: {
  isSelected: boolean;
  handleSelect: () => void;
  isDisabled?: boolean;
}) {
  const [popupDisabled, setPopupDisabled] = useState(false);

  function onClick() {
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
      <div
        className={
          "ml-auto flex select-none " + (!isDisabled ? " cursor-pointer" : "")
        }
        onClick={onClick}
      >
        <input
          className="cursor-pointer my-auto"
          type="checkbox"
          checked={isSelected}
          // dummy function to prevent warning
          onChange={() => null}
          disabled={isDisabled}
        />
      </div>
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
