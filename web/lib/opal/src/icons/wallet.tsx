import type { SVGProps } from "react";
const SvgWallet = (props: SVGProps<SVGSVGElement>) => (
  <svg
    viewBox="0 0 16 16"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    {...props}
  >
    <path
      d="M14 4.75H9C8.44772 4.75 8 5.19772 8 5.75L8 10.25C8 10.8023 8.44772 11.25 9 11.25H14M14 4.75C14.5523 4.75 15 5.19772 15 5.75V10.25C15 10.8023 14.5523 11.25 14 11.25M14 4.75V3.33333C14 2.6 13.4 2 12.6667 2H3.33333C2.6 2 2 2.6 2 3.33333V12.6667C2 13.4 2.6 14 3.33333 14H12.6667C13.4 14 14 13.4 14 12.6667L14 11.25M10.25 7V9"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);
export default SvgWallet;
