import React from "react";

interface LoadingSpinnerProps {
  size?: "small" | "medium" | "large";
  className?: string;
}

export function LoadingSpinner({
  size = "medium",
  className = "",
}: LoadingSpinnerProps) {
  const sizeClasses = {
    small: "h-4 w-4 border-2",
    medium: "h-6 w-6 border-2",
    large: "h-8 w-8 border-3",
  };

  return (
    <div className={`flex justify-center items-center ${className}`}>
      <div
        className={`${sizeClasses[size]} animate-spin rounded-full border-solid border-gray-300 border-t-gray-600 dark:border-gray-600 dark:border-t-gray-300`}
      />
    </div>
  );
}
