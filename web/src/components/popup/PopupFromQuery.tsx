import { useEffect } from "react";

import { usePopup } from "../admin/connectors/Popup";
import { PopupSpec } from "../admin/connectors/Popup";
import { useRouter } from "next/navigation";

interface PopupMessages {
  [key: string]: PopupSpec;
}

export const usePopupFromQuery = (messages: PopupMessages) => {
  const router = useRouter();
  const { popup, setPopup } = usePopup();

  useEffect(() => {
    const searchParams = new URLSearchParams(window.location.search);

    // Get the value for search param with key "message"
    const messageValue = searchParams?.get("message");

    // Check if any key from messages object is present in search params
    if (messageValue && messageValue in messages) {
      const popupMessage = messages[messageValue];
      router.replace(window.location.pathname);
      if (popupMessage !== undefined) {
        setPopup(popupMessage);
      }
    }
  }, []);

  return { popup };
};
