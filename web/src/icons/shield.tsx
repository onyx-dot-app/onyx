import * as React from "react";
import type { SVGProps } from "react";
const SvgShield = (props: SVGProps<SVGSVGElement>) => (
  <svg
    viewBox="0 0 16 16"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    {...props}
  >
    <path
      d="M8.00001 14.6667C8.00001 14.6667 13.3333 12 13.3333 8.00001V3.33334L8.00001 1.33334L2.66667 3.33334V8.00001C2.66667 12 8.00001 14.6667 8.00001 14.6667Z"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);
export default SvgShield;
