"use client";

import { useEffect } from "react";
import { usePopup } from "../admin/connectors/Popup";

const ERROR_MESSAGES = {
  Anonymous: "Your team does not have anonymous access enabled.",
};

export default function AuthErrorDisplay({
  searchParams,
}: {
  searchParams: any;
}) {
  const error = searchParams?.error;
  const { popup, setPopup } = usePopup();

  useEffect(() => {
    if (error) {
      setPopup({
        message:
          ERROR_MESSAGES[error as keyof typeof ERROR_MESSAGES] ||
          "An error occurred.",
        type: "error",
      });
    }
  }, [error]);

  return <>{popup}</>;
}
