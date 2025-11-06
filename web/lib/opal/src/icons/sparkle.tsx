import * as React from "react";
import type { SVGProps } from "react";
const SvgSparkle = (props: SVGProps<SVGSVGElement>) => (
  <svg
    viewBox="0 0 16 16"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    {...props}
  >
    <path
      d="M1.5 8C5.11111 6.91667 6.91667 5.11111 8 1.5C9.08333 5.11111 10.8889 6.91667 14.5 8C10.8889 9.08333 9.08333 10.8889 8 14.5C6.91667 10.8889 5.11111 9.08333 1.5 8Z"
      strokeWidth={1.5}
      strokeLinecap="square"
      strokeLinejoin="round"
    />
  </svg>
);
export default SvgSparkle;
