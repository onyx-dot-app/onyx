import React, { useState, useRef, useEffect, ReactNode } from "react";

interface PopupProps {
  children: JSX.Element;
  content: (
    close: () => void,
    ref?: React.RefObject<HTMLDivElement>
  ) => ReactNode;
  position?: "top" | "bottom" | "left" | "right";
  removePadding?: boolean;
}

const Popup: React.FC<PopupProps> = ({
  children,
  content,
  removePadding,
  position = "top",
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

  const getPopupStyle = (): React.CSSProperties => {
    if (!triggerRef.current) return {};

    const triggerRect = triggerRef.current.getBoundingClientRect();
    const popupStyle: React.CSSProperties = {
      position: "absolute",
      zIndex: 10,
    };

    switch (position) {
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
      default: // top
        popupStyle.bottom = `${triggerRect.height + 5}px`;
        popupStyle.left = `${triggerRect.width + 100}px`;
        popupStyle.transform = "translateX(-50%)";
    }

    return popupStyle;
  };

  return (
    <div className="relative inline-block">
      <div ref={triggerRef} onClick={togglePopup} className="cursor-pointer">
        {children}
      </div>

      {isOpen && (
        <div
          ref={popupRef}
          className={`absolute bg-white border border-gray-200 rounded-lg shadow-lg ${
            !removePadding && "p-4"
          } min-w-[400px]`}
          style={getPopupStyle()}
        >
          {content(closePopup, contentRef)}
        </div>
      )}
    </div>
  );
};

export default Popup;
