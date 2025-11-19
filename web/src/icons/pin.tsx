import * as React from "react";
import type { SVGProps } from "react";
const SvgPin = (props: SVGProps<SVGSVGElement>) => (
  <svg
    viewBox="0 0 16 16"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    {...props}
  >
    <path
      d="M6.70001 9.29581L2.20001 13.7958M6.70001 9.29581L9.99291 12.5887C10.6229 13.2187 11.7 12.7725 11.7 11.8816V10.5384C11.7 9.7428 12.0161 8.97974 12.5787 8.41713L13.4929 7.50292C13.8834 7.11239 13.8834 6.47923 13.4929 6.0887L9.90712 2.50292C9.51659 2.11239 8.88343 2.11239 8.49291 2.50292L7.57869 3.41713C7.01608 3.97974 6.25302 4.29581 5.45737 4.29581H4.11423C3.22332 4.29581 2.77715 5.37295 3.40712 6.00291L6.70001 9.29581Z"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);
export default SvgPin;
