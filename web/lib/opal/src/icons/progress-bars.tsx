import type { IconProps } from "@opal/types";
const SvgProgressBars = ({ size, ...props }: IconProps) => (
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
      d="M5.5 2.00003L13.25 2C13.9403 2 14.5 2.55964 14.5 3.25C14.5 3.94036 13.9403 4.5 13.25 4.5L5.5 4.50003M5.5 2.00003L2.74998 2C2.05963 2 1.49998 2.55964 1.49998 3.25C1.49998 3.94036 2.05963 4.5 2.74998 4.5L5.5 4.50003M5.5 2.00003V4.50003M10.5 11.5H13.25C13.9403 11.5 14.5 12.0596 14.5 12.75C14.5 13.4404 13.9403 14 13.25 14H10.5M10.5 11.5H2.74998C2.05963 11.5 1.49998 12.0596 1.49998 12.75C1.49998 13.4404 2.05963 14 2.74999 14H10.5M10.5 11.5V14M8 6.75H13.25C13.9403 6.75 14.5 7.30964 14.5 8C14.5 8.69036 13.9403 9.25 13.25 9.25H8M8 6.75H2.74998C2.05963 6.75 1.49998 7.30964 1.49998 8C1.49998 8.69036 2.05963 9.25 2.74998 9.25H8M8 6.75V9.25"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);
export default SvgProgressBars;
