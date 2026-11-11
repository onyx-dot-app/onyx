import type { IconProps } from "@opal/types";
const SvgPdfFile = ({ size, ...props }: IconProps) => (
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
      d="M1 8.5V5.5H2.7C3.52843 5.5 4.2 6.17157 4.2 7C4.2 7.82843 3.52843 8.5 2.7 8.5H1ZM1 8.5V10.5M15 5.5H11.8V8.5M11.8 8.5V10.5M11.8 8.5H14.5M14 11.5V12.67C14 13.4045 13.4045 14 12.67 14H3.33001C2.59547 14 2.00001 13.4045 2.00001 12.67M1.99999 3.33C1.99999 2.59546 2.59546 2 3.32999 2H12.67C13.4045 2 14 2.59546 14 3.33M6.4 5.5V10.5H8.1C8.92843 10.5 9.6 9.82843 9.6 9V7C9.6 6.17157 8.92843 5.5 8.1 5.5H6.4Z"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);
export default SvgPdfFile;
