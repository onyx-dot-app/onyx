import type { IconProps } from "@opal/types";

const SvgUploadSquare = ({ size, ...props }: IconProps) => (
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
      d="M11 14H12.6667C13.3929 14 14 13.3929 14 12.6667V3.33333C14 2.60711 13.3929 2 12.6667 2H3.33333C2.60711 2 2 2.60711 2 3.33333V12.6667C2 13.3929 2.60711 14 3.33333 14H5M10.6666 8.16667L7.99998 5.5M7.99998 5.5L5.33331 8.16667M7.99998 5.5V14"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);

export default SvgUploadSquare;
