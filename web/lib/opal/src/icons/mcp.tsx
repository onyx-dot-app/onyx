import type { IconProps } from "@opal/types";
const SvgMcp = ({ size, ...props }: IconProps) => (
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
      d="M8.46111 4.00011L5.53535 6.92584C4.55914 7.90205 4.55914 9.4848 5.53535 10.461C6.51155 11.4372 8.0943 11.4372 9.07051 10.461L11.9963 7.53528M7.30294 8.69306L10.2287 5.76732C11.2049 4.79111 11.2049 3.20837 10.2287 2.23216C9.25249 1.25595 7.66974 1.25595 6.69353 2.23216L2 6.92566M10.2287 5.76732C11.2049 4.79111 12.788 4.79148 13.7642 5.76769C14.7404 6.7439 14.7404 8.32665 13.7642 9.30286L9.42457 13.6432C9.22933 13.8384 9.22934 14.155 9.42459 14.3503L10.0743 15"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);
export default SvgMcp;
