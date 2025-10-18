import * as React from "react";
import type { SVGProps } from "react";

const SvgArrowWallRight = (props: SVGProps<SVGSVGElement>) => (
  <svg
    viewBox="0 0 15 12"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    {...props}
  >
    <path
      d="M8.44281 2.99998L10.8047 5.36191C10.9349 5.49208 11 5.6627 11 5.83331M8.44281 8.66665L10.8047 6.30471C10.9349 6.17455 11 6.00393 11 5.83331M1 5.83331H11M14 1V10.6667"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);

export default SvgArrowWallRight;
