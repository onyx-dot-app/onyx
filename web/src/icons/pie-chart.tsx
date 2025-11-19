import * as React from "react";
import type { SVGProps } from "react";
const SvgPieChart = (props: SVGProps<SVGSVGElement>) => (
  <svg
    viewBox="0 0 16 16"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    {...props}
  >
    <g clipPath="url(#clip0_76_2931)">
      <path
        d="M14.14 10.5933C13.7159 11.5963 13.0525 12.4802 12.2079 13.1675C11.3633 13.8549 10.3632 14.325 9.29496 14.5365C8.22674 14.7481 7.12295 14.6948 6.0801 14.3812C5.03725 14.0676 4.08709 13.5034 3.31268 12.7378C2.53828 11.9722 1.96321 11.0285 1.63776 9.98931C1.31231 8.95011 1.24638 7.847 1.44574 6.77643C1.64509 5.70586 2.10367 4.70043 2.78137 3.84803C3.45907 2.99563 4.33526 2.32222 5.33334 1.88668M14.6667 8.00001C14.6667 7.12453 14.4942 6.25762 14.1592 5.44879C13.8242 4.63995 13.3331 3.90502 12.7141 3.28597C12.095 2.66691 11.3601 2.17584 10.5512 1.84081C9.74239 1.50578 8.87548 1.33334 8 1.33334V8.00001H14.6667Z"
        strokeWidth={1.5}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </g>
    <defs>
      <clipPath id="clip0_76_2931">
        <rect width={16} height={16} fill="white" />
      </clipPath>
    </defs>
  </svg>
);
export default SvgPieChart;
