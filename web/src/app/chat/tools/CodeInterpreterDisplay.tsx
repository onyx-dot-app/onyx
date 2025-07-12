import React from "react";
import { FiCode } from "react-icons/fi";

interface CodeInterpreterDisplayProps {
  isCompleted?: boolean;
}

export default function CodeInterpreterDisplay({
  isCompleted = false,
}: CodeInterpreterDisplayProps) {
  return (
    <div className="flex items-center gap-2 p-3 bg-background-100 border border-background-200 rounded-lg">
      <FiCode size={16} className="text-text-500" />
      <span className="text-sm text-text-600">
        {isCompleted ? "Code execution completed" : "Executing code..."}
      </span>
    </div>
  );
}
