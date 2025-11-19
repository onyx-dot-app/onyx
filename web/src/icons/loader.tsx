import * as React from "react";
import type { SVGProps } from "react";

const SvgLoader = (props: SVGProps<SVGSVGElement>) => (
  <svg
    viewBox="0 0 15 15"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    {...props}
  >
    <path
      d="M7.41667 14.0833C3.73477 14.0833 0.75 11.0986 0.75 7.41667C0.75 3.73477 3.73477 0.75 7.41667 0.75C11.0986 0.75 14.0833 3.73477 14.0833 7.41667"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);

export default SvgLoader;
