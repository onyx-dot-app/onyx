import * as React from "react";
import type { SVGProps } from "react";

const SvgImport = (props: SVGProps<SVGSVGElement>) => (
  <svg
    viewBox="0 0 14 14"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    {...props}
  >
    <path
      d="M6.75 9.41667L9.41667 6.75M9.41667 6.75L6.75 4.08333M9.41667 6.75L0.75 6.74667M2.75 3.75V2.08C2.75 1.34546 3.34546 0.75 4.08 0.75H11.4167C11.7703 0.75 12.1094 0.890476 12.3595 1.14052C12.6095 1.39057 12.75 1.72971 12.75 2.08333V11.4167C12.75 11.7703 12.6095 12.1094 12.3595 12.3595C12.1094 12.6095 11.7703 12.75 11.4167 12.75H4.08C3.34546 12.75 2.75 12.1545 2.75 11.42V9.75"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);

export default SvgImport;
