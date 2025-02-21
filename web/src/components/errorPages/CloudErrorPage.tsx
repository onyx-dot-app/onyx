"use client";
import ErrorPageLayout from "./ErrorPageLayout";

export default function CloudError() {
  return (
    <ErrorPageLayout>
      <h1 className="text-2xl font-semibold mb-4 text-gray-800 dark:text-gray-200">
        Maintenance in Progress
      </h1>
      <div className="space-y-4 text-gray-600 dark:text-gray-300">
        <p>
          Onyx is currently in a maintenance window. Please check back in a
          couple of minutes.
        </p>
        <p>
          We apologize for any inconvenience this may cause and appreciate your
          patience.
        </p>
      </div>
    </ErrorPageLayout>
  );
}
