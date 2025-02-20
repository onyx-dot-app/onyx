"use client";
import React, {
  useState,
  useRef,
  useEffect,
  ReactNode,
  useContext,
} from "react";
import { SettingsContext } from "../settings/SettingsProvider";

interface PopupProps {
  children: JSX.Element;
  content: (
    close: () => void,
    ref?: React.RefObject<HTMLDivElement>
  ) => ReactNode;
  position?: "top" | "bottom" | "left" | "right" | "top-right";
  removePadding?: boolean;
  tab?: boolean;
  flexPriority?: "shrink" | "stiff" | "second";
  mobilePosition?: "top" | "bottom" | "left" | "right" | "top-right";
}

const Popup: React.FC<PopupProps> = ({
  children,
  content,
  tab,
  removePadding,
  position = "top",
  flexPriority,
  mobilePosition,
}) => {
  const [isOpen, setIsOpen] = useState<boolean>(false);
  const triggerRef = useRef<HTMLDivElement>(null);
  const popupRef = useRef<HTMLDivElement>(null);
  const contentRef = useRef<HTMLDivElement>(null);

  const togglePopup = (): void => {
    setIsOpen(!isOpen);
  };

  const closePopup = (): void => {
    setIsOpen(false);
  };

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (
        popupRef.current &&
        !popupRef.current.contains(event.target as Node) &&
        triggerRef.current &&
        !triggerRef.current.contains(event.target as Node) &&
        (!contentRef.current ||
          !contentRef.current.contains(event.target as Node))
      ) {
        closePopup();
      }
    };

    document.addEventListener("mousedown", handleClickOutside);
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
    };
  }, []);

  const settings = useContext(SettingsContext);

  const getPopupStyle = (): React.CSSProperties => {
    if (!triggerRef.current) return {};

    const triggerRect = triggerRef.current.getBoundingClientRect();
    const popupStyle: React.CSSProperties = {
      position: "absolute",
      zIndex: 10,
    };

    const currentPosition = settings?.isMobile
      ? mobilePosition || position
      : position;

    switch (currentPosition) {
      case "bottom":
        popupStyle.top = `${triggerRect.height + 5}px`;
        popupStyle.left = "50%";
        popupStyle.transform = "translateX(-50%)";
        break;
      case "left":
        popupStyle.top = "50%";
        popupStyle.right = `${triggerRect.width + 5}px`;
        popupStyle.transform = "translateY(-50%)";
        break;
      case "right":
        popupStyle.top = "50%";
        popupStyle.left = `${triggerRect.width + 5}px`;
        popupStyle.transform = "translateY(-50%)";
        break;
      case "top-right":
        popupStyle.bottom = `${triggerRect.height + 5}px`;
        popupStyle.right = "0";
        popupStyle.right = "auto";
        break;
      default: // top
        popupStyle.bottom = `${triggerRect.height + 5}px`;
        popupStyle.left = "50%";
        popupStyle.transform = "translateX(-50%)";
    }

    return popupStyle;
  };

  return (
    <div
      className={`relative inline-block
      ${
        flexPriority === "shrink" &&
        "flex-shrink-100 flex-grow-0 flex-basis-auto min-w-[30px] whitespace-nowrap "
      }
      ${
        flexPriority === "second" &&
        "flex-shrink flex-basis-0 min-w-[30px] whitespace-nowrap "
      }
      ${flexPriority === "stiff" && "flex-none whitespace-nowrap "}
`}
    >
      <div ref={triggerRef} onClick={togglePopup} className="cursor-pointer">
        {children}
      </div>

      {isOpen && (
        <div
          ref={popupRef}
          className={`absolute bg-white border border-background-200  rounded-lg shadow-lg ${
            !removePadding && "p-4"
          } ${
            !settings?.isMobile
              ? tab
                ? "w-[400px] "
                : "min-w-[400px]"
              : "w-[250px]"
          }`}
          style={getPopupStyle()}
        >
          {content(closePopup, contentRef)}
        </div>
      )}
    </div>
  );
};

export default Popup;
