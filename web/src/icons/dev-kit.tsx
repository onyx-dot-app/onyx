import * as React from "react";
import type { SVGProps } from "react";
const SvgDevKit = (props: SVGProps<SVGSVGElement>) => (
  <svg
    viewBox="0 0 16 16"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    {...props}
  >
    <path
      d="M2 5H14M2 5V14H14V5M2 5C2 4.67722 2.11475 4.36495 2.32376 4.11897L4.12423 2H11.8795L13.6766 4.11869C13.8854 4.36487 14 4.67719 14 5M9.66666 11.1733L11.3333 9.50667L9.66666 7.84M6.33333 7.84L4.66666 9.50667L6.33333 11.1733"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);
export default SvgDevKit;
