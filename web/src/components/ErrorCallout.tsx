import i18n from "@/i18n/init";
import k from "./i18n/keys";
import { FiAlertTriangle } from "react-icons/fi";

export function ErrorCallout({
  errorTitle,
  errorMsg,
}: {
  errorTitle?: string;
  errorMsg?: string;
}) {
  return (
    <div>
      <Callout
        className="mt-4"
        title={errorTitle || i18n.t(k.PAGE_NOT_FOUND)}
        icon={<FiAlertTriangle className="text-red-500 h-5 w-5" />}
        type="danger"
      >
        {errorMsg}
      </Callout>
    </div>
  );
}
