import type { IconProps } from "@opal/types";
const SvgUserEdit = ({ size, ...props }: IconProps) => (
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
      d="M1 14C1 13.6667 1 13.3333 1 13C1 11.3431 2.34316 10 4.00002 10H7M8.75 4.75C8.75 6.26878 7.51878 7.5 6 7.5C4.48122 7.5 3.25 6.26878 3.25 4.75C3.25 3.23122 4.48122 2 6 2C7.51878 2 8.75 3.23122 8.75 4.75ZM12.09 8.41421C12.3552 8.149 12.7149 8 13.09 8C13.2757 8 13.4596 8.03658 13.6312 8.10765C13.8028 8.17872 13.9587 8.28289 14.09 8.41421C14.2213 8.54554 14.3255 8.70144 14.3966 8.87302C14.4676 9.0446 14.5042 9.2285 14.5042 9.41421C14.5042 9.59993 14.4676 9.78383 14.3966 9.95541C14.3255 10.127 14.2213 10.2829 14.09 10.4142L10.6667 13.8333L8 14.5L8.66667 11.8333L12.09 8.41421Z"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);
export default SvgUserEdit;
