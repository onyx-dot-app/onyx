import * as React from "react";
import type { SVGProps } from "react";

const SvgCalendar = (props: SVGProps<SVGSVGElement>) => (
  <svg
    viewBox="0 0 14 15"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    {...props}
  >
    <path
      d="M9.41667 0.75V3.41667M4.08333 0.75V3.41667M0.75 6.08333H12.75M2.08333 2.08333H11.4167C12.153 2.08333 12.75 2.68029 12.75 3.41667V12.75C12.75 13.4864 12.153 14.0833 11.4167 14.0833H2.08333C1.34695 14.0833 0.75 13.4864 0.75 12.75V3.41667C0.75 2.68029 1.34695 2.08333 2.08333 2.08333Z"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);

export default SvgCalendar;
