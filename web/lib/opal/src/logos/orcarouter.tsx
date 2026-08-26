import React from "react";
import type { IconProps } from "@opal/types";

// OrcaRouter wordmark fluke: a stylized orca tail that doubles as a router
// node-graph (three tips feeding a single stem). Gradient id is per-instance so
// repeated renders don't collide.
const SvgOrcarouter = ({ size, ...props }: IconProps) => {
  const gradientId = React.useId();
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      {...props}
    >
      <title>OrcaRouter</title>
      <path
        d="M12 3.5C10.5 4.5 8 6 5.5 6.8C2.5 7.8 0.5 8 0.5 8.8C0.5 9.6 3 9.6 6 9.4C8.5 9.2 10.5 10 12 13C13.5 10 15.5 9.2 18 9.4C21 9.6 23.5 9.6 23.5 8.8C23.5 8 21.5 7.8 18.5 6.8C16 6 13.5 4.5 12 3.5Z"
        fill={`url(#${gradientId})`}
      />
      <defs>
        <linearGradient
          id={gradientId}
          x1="0.5"
          y1="3.5"
          x2="23.5"
          y2="13"
          gradientUnits="userSpaceOnUse"
        >
          <stop offset="0" stopColor="#0B1220" />
          <stop offset="1" stopColor="#3B82F6" />
        </linearGradient>
      </defs>
    </svg>
  );
};

export default SvgOrcarouter;
