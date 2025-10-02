import * as React from "react";
import type { SVGProps } from "react";
const SvgWorkflow = (props: SVGProps<SVGSVGElement>) => (
  <svg
    viewBox="0 0 16 16"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    {...props}
  >
    <path
      d="M2.79986 5.60004C2.61157 5.85073 2.5 6.16234 2.5 6.5V11.9754C2.5 13.203 4.08461 13.6951 4.78005 12.6836L11.2199 3.31644C11.9154 2.30488 13.5 2.79705 13.5 4.0246V9.5C13.5 9.83766 13.3884 10.1493 13.2001 10.4M2.79986 5.60004C3.13415 5.85118 3.54969 6 4 6C5.10457 6 6 5.10457 6 4C6 2.89543 5.10457 2 4 2C2.89543 2 2 2.89543 2 4C2 4.65426 2.31416 5.23515 2.79986 5.60004ZM13.2001 10.4C12.8659 10.1488 12.4503 10 12 10C10.8954 10 10 10.8954 10 12C10 13.1046 10.8954 14 12 14C13.1046 14 14 13.1046 14 12C14 11.3457 13.6858 10.7648 13.2001 10.4Z"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);
export default SvgWorkflow;
