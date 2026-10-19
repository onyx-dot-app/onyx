import type { IconProps } from "@opal/types";

const SvgDownload = ({ size, ...props }: IconProps) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 16 16"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    stroke="currentColor"
    {...props}
  >
    <path
      d="M14 10V12.6667C14 13.3929 13.3929 14 12.6667 14H3.33333C2.60711 14 2 13.3929 2 12.6667V10M4.66667 6.66667L8 10M8 10L11.3333 6.66667M8 10L8 2"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);
export default SvgDownload;
