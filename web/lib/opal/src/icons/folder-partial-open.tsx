import React from "react";
import type { IconProps } from "@opal";

const SvgFolderPartialOpen = React.forwardRef<SVGSVGElement, IconProps>(
  ({ size = 32, color = "currentColor", title, className, ...props }, ref) => (
    <svg
      ref={ref}
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 16 13"
      width={size}
      height={size}
      fill="none"
      role={title ? "img" : "presentation"}
      aria-label={title}
      className={className}
      stroke="currentColor"
      {...props}
    >
      {title ? <title>{title}</title> : null}
      <path
        d="M14.1431 4.98782V4.25C14.1431 3.42157 13.4715 2.75 12.6431 2.75H8.76442C8.36659 2.75 7.98506 2.59196 7.70376 2.31066L6.58244 1.18934C6.30113 0.908035 5.9196 0.75 5.52178 0.75H2.6431C1.81467 0.75 1.1431 1.42157 1.1431 2.25V4.9878"
        stroke={color}
        strokeWidth={1.5}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path
        d="M14.2394 10.3532C14.1852 11.1397 13.5313 11.75 12.743 11.75H2.54321C1.75483 11.75 1.101 11.1397 1.04676 10.3532L0.753657 6.1032C0.693864 5.23621 1.38105 4.5 2.2501 4.5H13.0361C13.9051 4.5 14.5923 5.2362 14.5325 6.1032L14.2394 10.3532Z"
        stroke={color}
        strokeWidth={1.5}
        strokeLinecap="round"
      />
    </svg>
  )
);

SvgFolderPartialOpen.displayName = "SvgFolderPartialOpen";
export default SvgFolderPartialOpen;
