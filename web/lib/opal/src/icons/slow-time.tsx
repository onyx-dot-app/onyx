import type { IconProps } from "@opal/types";
const SvgSlowTime = ({ size, ...props }: IconProps) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 16 16"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    stroke="currentColor"
    {...props}
  >
    <g clipPath="url(#clip0_997_17795)">
      <path
        d="M8 4.00001V8.00001L11 9.5M13.1404 12.2453C11.9176 13.7243 10.0689 14.6667 7.99999 14.6667C6.70211 14.6667 5.49086 14.2958 4.46643 13.6542M14.4826 9.5624C14.6029 9.06125 14.6667 8.53806 14.6667 7.99999C14.6667 4.83387 12.4596 2.18324 9.5 1.50275M6.5 1.50275C5.76902 1.67082 5.08394 1.95908 4.46668 2.3456M2.34559 4.4667C1.95907 5.08396 1.67082 5.76903 1.50275 6.50001M1.50276 9.50001C1.67083 10.231 1.95909 10.916 2.34561 11.5333"
        strokeWidth={1.5}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </g>
    <defs>
      <clipPath id="clip0_997_17795">
        <rect width={16} height={16} fill="white" />
      </clipPath>
    </defs>
  </svg>
);
export default SvgSlowTime;
