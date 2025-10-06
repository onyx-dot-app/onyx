import * as React from "react";
import type { SVGProps } from "react";
const SvgHourglass = (props: SVGProps<SVGSVGElement>) => (
  <svg
    viewBox="0 0 16 16"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    {...props}
  >
    <path
      d="M8 7.99999L4.44793 5.72667C4.06499 5.48159 3.83333 5.05828 3.83333 4.60364V1.83333H12.1667V4.60364C12.1667 5.05828 11.935 5.48159 11.5521 5.72667L8 7.99999ZM8 7.99999L11.5521 10.2733C11.935 10.5184 12.1667 10.9417 12.1667 11.3963V14.1667H3.83333V11.3963C3.83333 10.9417 4.06499 10.5184 4.44793 10.2733L8 7.99999ZM13.5 14.1667H2.5M13.5 1.83333H2.5"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);
export default SvgHourglass;
