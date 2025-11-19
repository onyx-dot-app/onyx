import * as React from "react";
import type { SVGProps } from "react";
const SvgEditBig = (props: SVGProps<SVGSVGElement>) => (
  <svg
    viewBox="0 0 16 16"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    {...props}
  >
    <path
      d="M8 2.5H4C3.17157 2.5 2.5 3.17157 2.5 4V12C2.5 12.8284 3.17157 13.5 4 13.5H12C12.8284 13.5 13.5 12.8284 13.5 12V8M6 10V8.26485C6 8.08682 6.0707 7.91617 6.19654 7.79028L11.5938 2.3931C12.1179 1.86897 12.9677 1.86897 13.4918 2.3931L13.6069 2.50823C14.131 3.03236 14.131 3.88213 13.6069 4.40626L8.20971 9.80345C8.08389 9.92934 7.91317 10 7.73521 10H6Z"
      strokeWidth={1.5}
      strokeLinejoin="round"
    />
  </svg>
);
export default SvgEditBig;
