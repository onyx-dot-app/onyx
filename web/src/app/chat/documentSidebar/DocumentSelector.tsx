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

  function onClick(e: React.MouseEvent<HTMLInputElement>) {
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
      <label
        className={
          "ml-auto flex select-none " + (!isDisabled ? " cursor-pointer" : "")
        }
      >
        <input
          className="cursor-pointer my-auto"
          type="checkbox"
          checked={isSelected}
          onChange={(e) => {
            e.stopPropagation();
            if (!isDisabled) {
              setPopupDisabled(true);
              handleSelect();
              // re-enable popup after 1 second so that we don't show the popup immediately upon the
              // user de-selecting document
              setTimeout(() => {
                setPopupDisabled(false);
              }, 1000);
            }
          }}
          disabled={isDisabled}
        />
      </label>
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
