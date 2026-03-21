"use client";

import { useEffect } from "react";
import { toast } from "@/hooks/useToast";

const ERROR_MESSAGES = {
  Anonymous: "Tu equipo no tiene acceso anonimo habilitado.",
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
          "Ocurrio un error."
      );
    }
  }, [error]);

  return null;
}
