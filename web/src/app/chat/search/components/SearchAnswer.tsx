import React from "react";
import { FiInfo } from "react-icons/fi";

interface SearchAnswerProps {
  answer: string | null;
  isLoading: boolean;
  error: string | null;
}

export function SearchAnswer({ answer, isLoading, error }: SearchAnswerProps) {
  if (error) {
    return (
      <div className="bg-red-50 border border-red-200 rounded-lg p-4 mb-4">
        <div className="flex items-start">
          <div className="flex-shrink-0 text-red-500">
            <FiInfo size={20} />
          </div>
          <div className="ml-3">
            <h3 className="text-sm font-medium text-red-800">Error</h3>
            <div className="mt-2 text-sm text-red-700">
              <p>{error}</p>
            </div>
          </div>
        </div>
      </div>
    );
  }

  if (isLoading && !answer) {
    return (
      <div className="bg-white border border-gray-200 rounded-lg p-4 mb-4 shadow-sm">
        <div className="animate-pulse">
          <div className="h-4 bg-gray-200 rounded w-3/4 mb-2"></div>
          <div className="h-4 bg-gray-200 rounded w-full mb-2"></div>
          <div className="h-4 bg-gray-200 rounded w-5/6 mb-2"></div>
          <div className="h-4 bg-gray-200 rounded w-2/3"></div>
        </div>
      </div>
    );
  }

  if (!answer) {
    return null;
  }

  return (
    <div className="bg-white border border-gray-200 rounded-lg p-4 mb-4 shadow-sm">
      <h3 className="text-sm font-medium text-gray-900 mb-2">Answer</h3>
      <div className="text-sm text-gray-700 whitespace-pre-line">{answer}</div>
    </div>
  );
}
