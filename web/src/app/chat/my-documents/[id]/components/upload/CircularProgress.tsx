import React, { useEffect, useState } from "react";
import { Check } from "lucide-react";

interface CircularProgressProps {
  progress: number; // 0 to 100
  size?: number;
  strokeWidth?: number;
  showPercentage?: boolean;
}

export const CircularProgress: React.FC<CircularProgressProps> = ({
  progress,
  size = 16,
  strokeWidth = 2,
  showPercentage = false,
}) => {
  const [displayedProgress, setDisplayedProgress] = useState(progress);
  const [showComplete, setShowComplete] = useState(false);

  // Smooth progress transitions by gradually updating the displayed value
  useEffect(() => {
    // If we're going to 100%, handle special completion animation
    if (progress >= 100 && displayedProgress < 100) {
      // First complete the circle
      const timer = setTimeout(() => {
        setDisplayedProgress(100);
        // Then show the checkmark after circle is complete
        setTimeout(() => setShowComplete(true), 400);
      }, 200);
      return () => clearTimeout(timer);
    }

    // For normal progress updates, smooth the transition
    if (progress > displayedProgress) {
      const diff = progress - displayedProgress;
      const increment = Math.max(1, Math.min(diff / 2, 5)); // Smoothing factor

      const timer = setTimeout(() => {
        setDisplayedProgress((prev) => Math.min(progress, prev + increment));
      }, 50);
      return () => clearTimeout(timer);
    }
  }, [progress, displayedProgress]);

  const radius = (size - strokeWidth) / 2;
  const circumference = radius * 2 * Math.PI;
  const strokeDashoffset =
    circumference - (displayedProgress / 100) * circumference;

  // Animation class for completion
  const completionClass = showComplete
    ? "scale-100 opacity-100"
    : "scale-0 opacity-0";

  return (
    <div className="relative flex items-center justify-center">
      {/* Progress circle */}
      <svg
        width={size}
        height={size}
        viewBox={`0 0 ${size} ${size}`}
        className={`transform -rotate-90 transition-opacity duration-300 ${
          showComplete ? "opacity-0" : "opacity-100"
        }`}
      >
        {/* Background circle */}
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          stroke="currentColor"
          strokeOpacity={0.2}
          strokeWidth={strokeWidth}
          fill="none"
        />
        {/* Progress circle */}
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          stroke="currentColor"
          strokeWidth={strokeWidth}
          fill="none"
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={strokeDashoffset}
          className={`text-blue-500 dark:text-blue-400 transition-all duration-300 ease-out ${
            displayedProgress >= 100 ? "text-green-500 dark:text-green-400" : ""
          }`}
        />
      </svg>

      {/* Check mark for completion */}
      <div
        className={`absolute inset-0 flex items-center justify-center transition-all duration-300 ${completionClass}`}
      >
        <Check
          className="text-green-500 dark:text-green-400"
          size={size * 0.7}
          strokeWidth={strokeWidth + 1}
        />
      </div>

      {/* Percentage label */}
      {showPercentage && !showComplete && (
        <span className="absolute text-[8px] font-medium">
          {Math.round(displayedProgress)}%
        </span>
      )}
    </div>
  );
};
