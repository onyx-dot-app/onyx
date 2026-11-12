import React from "react";
import type { IconProps } from "@opal/types";

const SvgGoogleDrive = ({ size, ...props }: IconProps) => {
  const id = React.useId();
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 16 16"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      {...props}
    >
      <path
        d="M11.9116 4.46151L10.2942 7.26226L7.99944 11.2362L9.61816 14.0396L11.8355 14.0396C14.327 14.0396 15.8842 11.3425 14.6385 9.18474L11.9116 4.46151Z"
        fillRule="evenodd"
        clipRule="evenodd"
        fill={`url(#${id}-paint0)`}
      />
      <path
        d="M9.61816 14.0396L7.99944 11.2362L5.70484 7.26226L2.47174 7.26174L1.3615 9.18474C0.115782 11.3425 1.67298 14.0396 4.1645 14.0396H9.61816Z"
        fillRule="evenodd"
        clipRule="evenodd"
        fill={`url(#${id}-paint1)`}
      />
      <path
        d="M11.9116 4.46151L10.803 2.54135C9.55723 0.38361 6.44276 0.383695 5.19704 2.54135L2.46797 7.26226H5.70484H10.2942L11.9116 4.46151Z"
        fillRule="evenodd"
        clipRule="evenodd"
        fill={`url(#${id}-paint2)`}
      />
      <defs>
        <linearGradient
          id={`${id}-paint0`}
          x1={16.3128}
          y1={13.4944}
          x2={8.60391}
          y2={8.86196}
          gradientUnits="userSpaceOnUse"
        >
          <stop offset={0.09} stopColor="#FFE921" />
          <stop offset={1} stopColor="#FEC700" />
        </linearGradient>
        <linearGradient
          id={`${id}-paint1`}
          x1={9.5672}
          y1={14.858}
          x2={1.14628}
          y2={9.76391}
          gradientUnits="userSpaceOnUse"
        >
          <stop offset={0.15} stopColor="#A9A8FF" />
          <stop offset={0.33} stopColor="#6D97FF" />
          <stop offset={0.48} stopColor="#3186FF" />
        </linearGradient>
        <linearGradient
          id={`${id}-paint2`}
          x1={10.8005}
          y1={2.61632}
          x2={2.26799}
          y2={6.59895}
          gradientUnits="userSpaceOnUse"
        >
          <stop offset={0.55} stopColor="#0EBC5F" />
          <stop offset={0.85} stopColor="#78C9FF" />
        </linearGradient>
      </defs>
    </svg>
  );
};

export default SvgGoogleDrive;
