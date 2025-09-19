"use client";
import { useTranslation } from "@/hooks/useTranslation";
import k from "@/i18n/keys";
import { FiAlertTriangle } from "react-icons/fi";
import { Callout } from "./ui/callout";

export function ErrorCallout({
  errorTitle,
  errorMsg,
}: {
  errorTitle?: string;
  errorMsg?: string;
}) {
  const { t } = useTranslation();

  return (
    <div>
      <Callout
        className="mt-4"
        title={errorTitle || t(k.PAGE_NOT_FOUND)}
        icon={<FiAlertTriangle className="text-red-500 h-5 w-5" />}
        type="danger"
      >
        {errorMsg}
      </Callout>
    </div>
  );
}
