"use client";

import { useEffect } from "react";
import { toast } from "@/hooks/useToast";

const ERROR_MESSAGES = {
  Anonymous: "Your team does not have anonymous access enabled.",
};

export default function AuthErrorDisplay({
  searchParams,
}: {
  searchParams: any;
}) {
  const error = searchParams?.error;

  useEffect(() => {
    if (error) {
      toast.error(
        ERROR_MESSAGES[error as keyof typeof ERROR_MESSAGES] ||
          "An error occurred."
      );
    }
  }, [error]);

  return null;
}
