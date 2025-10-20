import * as React from "react";
import type { SVGProps } from "react";
const SvgStop = (props: SVGProps<SVGSVGElement>) => (
  <svg
    viewBox="0 0 16 16"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    {...props}
  >
    <path
      d="M12 4H4V12H12V4Z"
      strokeWidth={1.5}
      fill="var(--background-tint-00)"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);
export default SvgStop;
