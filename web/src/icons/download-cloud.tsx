import * as React from "react";
import type { SVGProps } from "react";

const SvgDownloadCloud = (props: SVGProps<SVGSVGElement>) => (
  <svg
    viewBox="0 0 16 16"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    {...props}
  >
    <g clipPath="url(#clip0_download_cloud)">
      <path
        d="M12 6.66669H11.16C10.9106 5.70069 10.3952 4.82401 9.67243 4.13628C8.94966 3.44856 8.04848 2.97735 7.07128 2.7762C6.09409 2.57506 5.08007 2.65205 4.14444 2.99842C3.20881 3.34478 2.3891 3.94664 1.77844 4.73561C1.16778 5.52457 0.790662 6.469 0.689941 7.46159C0.589219 8.45417 0.76893 9.45511 1.20865 10.3507C1.64838 11.2462 2.33048 12.0005 3.17746 12.5277C4.02443 13.055 5.00232 13.3341 6 13.3334H12C12.8841 13.3334 13.7319 12.9822 14.357 12.357C14.9821 11.7319 15.3333 10.8841 15.3333 10C15.3333 9.11597 14.9821 8.26812 14.357 7.643C13.7319 7.01788 12.8841 6.66669 12 6.66669Z"
        strokeWidth={1.5}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path
        d="M8 10.6667L8 5.33337M8 10.6667L5.33333 8.00004M8 10.6667L10.6667 8.00004"
        strokeWidth={1.5}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </g>
    <defs>
      <clipPath id="clip0_download_cloud">
        <rect width={16} height={16} fill="white" />
      </clipPath>
    </defs>
  </svg>
);

export default SvgDownloadCloud;
