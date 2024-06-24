import { useRef, useState } from "react";

export interface PopupSpec {
  message: string;
  type: "success" | "error";
}

export const Popup: React.FC<PopupSpec> = ({ message, type }) => (
  <div
    className={`fixed bottom-4 left-4 p-4 rounded-md shadow-lg text-white z-[100] ${
      type === "success" ? "bg-green-500" : "bg-error"
    }`}
  >
    {message}
  </div>
);

export const usePopup = () => {
  const [popup, setPopup] = useState<PopupSpec | null>(null);
  // using NodeJS.Timeout because setTimeout in NodeJS returns a different type than in browsers
  const timeoutRef = useRef<NodeJS.Timeout | null>(null);

  const setPopupWithExpiration = (popupSpec: PopupSpec | null) => {
    // Clear any previous timeout
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current);
    }

    setPopup(popupSpec);
    timeoutRef.current = setTimeout(() => {
      setPopup(null);
    }, 4000);
  };

  return {
    popup: popup && <Popup {...popup} />,
    setPopup: setPopupWithExpiration,
  };
};
