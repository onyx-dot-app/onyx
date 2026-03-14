import type { IconProps } from "@opal/types";
const SvgUserKey = ({ size, ...props }: IconProps) => (
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
      d="M1 14C1 13.6667 1 13.3333 1 13C1 11.3431 2.34316 10 4.00002 10H8.5M12.625 10C13.6605 10 14.5 9.16053 14.5 8.125C14.5 7.08947 13.6605 6.25 12.625 6.25C11.5895 6.25 10.75 7.08947 10.75 8.125C10.75 9.16053 11.5895 10 12.625 10ZM12.625 10V12.25M12.625 14.5V13.5M12.625 13.5H13.875V12.25H12.625M12.625 13.5V12.25M8.75 4.75C8.75 6.26878 7.51878 7.5 6 7.5C4.48122 7.5 3.25 6.26878 3.25 4.75C3.25 3.23122 4.48122 2 6 2C7.51878 2 8.75 3.23122 8.75 4.75Z"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);
export default SvgUserKey;
