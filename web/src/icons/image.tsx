import * as React from "react";
import type { SVGProps } from "react";
const SvgImage = (props: SVGProps<SVGSVGElement>) => (
  <svg
    viewBox="0 0 16 16"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    {...props}
  >
    <path
      d="M11 14L6.06066 9.06072C5.47487 8.47498 4.52513 8.47498 3.93934 9.06072L2 11M2 3.49998C2 2.67156 2.67157 2 3.5 2H12.5C13.3285 2 14 2.67156 14 3.49998V12.4999C14 13.3283 13.3285 13.9998 12.5 13.9998H3.5C2.67157 13.9998 2 13.3283 2 12.4999V3.49998ZM9.875 7.62492C10.7034 7.62492 11.375 6.95338 11.375 6.12494C11.375 5.29653 10.7034 4.62496 9.875 4.62496C9.04655 4.62496 8.375 5.29653 8.375 6.12494C8.375 6.95338 9.04655 7.62492 9.875 7.62492Z"
      strokeWidth={1.5}
      strokeLinecap="round"
    />
  </svg>
);
export default SvgImage;
