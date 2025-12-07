import * as React from "react";
import type { SVGProps } from "react";

const SvgBracketCurly = (props: SVGProps<SVGSVGElement>) => (
  <svg
    viewBox="0 0 15 14"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    {...props}
  >
    <path
      d="M4.25 0.750024C3.14543 0.750024 2.25 1.64545 2.25 2.75002V4.67966C2.25 5.34836 1.9158 5.97283 1.3594 6.34376L0.75 6.75002L1.3594 7.15629C1.9158 7.52722 2.25 8.15169 2.25 8.82039V10.75C2.25 11.8546 3.14543 12.75 4.25 12.75M10.25 12.75C11.3546 12.75 12.25 11.8546 12.25 10.75V8.82038C12.25 8.15167 12.5842 7.5272 13.1406 7.15627L13.75 6.75002L13.1406 6.34373C12.5842 5.9728 12.25 5.34835 12.25 4.67965V2.75C12.25 1.64543 11.3546 0.75 10.25 0.75"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);

export default SvgBracketCurly;
