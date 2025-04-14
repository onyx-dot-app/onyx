import i18n from "i18next";
import k from "./../../../../i18n/keys";
import { FiInfo } from "react-icons/fi";

export default function DeletionErrorStatus({
  deletion_failure_message,
}: {
  deletion_failure_message: string;
}) {
  return (
    <div className="mt-2 rounded-md border border-error-300 bg-error-50 p-4 text-error-600 max-w-3xl">
      <div className="flex items-center">
        <h3 className="text-base font-medium">{i18n.t(k.DELETION_ERROR)}</h3>
        <div className="ml-2 relative group">
          <FiInfo className="h-4 w-4 text-error-600 cursor-help" />
          <div className="absolute z-10 w-64 p-2 mt-2 text-sm bg-white rounded-md shadow-lg opacity-0 group-hover:opacity-100 transition-opacity duration-300 border border-background-200">
            {i18n.t(k.THIS_ERROR_OCCURRED_WHILE_ATTE)}
          </div>
        </div>
      </div>
      <div className="mt-2 text-sm">
        <p>{deletion_failure_message}</p>
      </div>
    </div>
  );
}
