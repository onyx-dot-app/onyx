"use client";
import i18n from "@/i18n/init";
import k from "./../../i18n/keys";
import ErrorPageLayout from "./ErrorPageLayout";

export default function CloudError() {
  return (
    <ErrorPageLayout>
      <h1 className="text-2xl font-semibold mb-4 text-gray-800 dark:text-gray-200">
        {i18n.t(k.MAINTENANCE_IN_PROGRESS)}
      </h1>
      <div className="space-y-4 text-gray-600 dark:text-gray-300">
        <p>{i18n.t(k.ONYX_IS_CURRENTLY_IN_A_MAINTEN)}</p>
        <p>{i18n.t(k.WE_APOLOGIZE_FOR_ANY_INCONVENI)}</p>
      </div>
    </ErrorPageLayout>
  );
}
