import * as React from "react";
import type { SVGProps } from "react";
const SvgPlug = (props: SVGProps<SVGSVGElement>) => (
  <svg
    viewBox="0 0 16 16"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    {...props}
  >
    <path
      d="M12 10.5H15M12 10.5V12.5M12 10.5V5.5M12 3.5H8.5C6.01472 3.5 4 5.51472 4 8M12 3.5V5.5M12 3.5V2M12 12.5H8.5C6.01472 12.5 4 10.4853 4 8M12 12.5V14M4 8H1M12 5.5H15"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);
export default SvgPlug;
