import * as React from "react";
import type { SVGProps } from "react";

const SvgArrowExchange = (props: SVGProps<SVGSVGElement>) => (
  <svg
    viewBox="0 0 12 13"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    {...props}
  >
    <path
      d="M2.97381 0.75L0.945267 2.77854C0.81509 2.90871 0.750002 3.07932 0.750001 3.24994M2.97392 5.75L0.94526 3.72134C0.815087 3.59117 0.75 3.42056 0.750001 3.24994M10.75 3.24994H0.750001M8.52613 6.75003L10.5547 8.77858C10.6849 8.90875 10.75 9.07936 10.75 9.24998M8.52613 11.75L10.5547 9.72138C10.6849 9.59121 10.75 9.4206 10.75 9.24998M0.75 9.24998H10.75"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);

export default SvgArrowExchange;
