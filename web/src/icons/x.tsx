import * as React from "react";
import type { SVGProps } from "react";
const SvgX = (props: SVGProps<SVGSVGElement>) => (
  <svg
    viewBox="0 0 28 28"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    {...props}
  >
    <path d="M21 7L7 21M7 7L21 21" strokeWidth={2} strokeLinejoin="round" />
  </svg>
);
export default SvgX;
