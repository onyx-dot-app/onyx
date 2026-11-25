import type { IconProps } from "@opal/types";
// A generic mark for a network file share: a folder on a network line.
const SvgFileShare = ({ size, ...props }: IconProps) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 52 52"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    {...props}
  >
    <path
      d="M6 11C6 9.34315 7.34315 8 9 8H19.6C20.4 8 21.2 8.32 21.75 8.9L25.5 12.5H43C44.6569 12.5 46 13.8431 46 15.5V19H6V11Z"
      fill="#2F6FCF"
    />
    <path
      d="M6 19C6 17.3431 7.34315 16 9 16H43C44.6569 16 46 17.3431 46 19V32C46 33.6569 44.6569 35 43 35H9C7.34315 35 6 33.6569 6 32V19Z"
      fill="#5AA0F5"
    />
    <path
      d="M24.5 35H27.5V39H29C30.1046 39 31 39.8954 31 41V42H44.5C45.3284 42 46 42.6716 46 43.5C46 44.3284 45.3284 45 44.5 45H31V46C31 47.1046 30.1046 48 29 48H23C21.8954 48 21 47.1046 21 46V45H7.5C6.67157 45 6 44.3284 6 43.5C6 42.6716 6.67157 42 7.5 42H21V41C21 39.8954 21.8954 39 23 39H24.5V35Z"
      className="fill-[#1F3B63] dark:fill-(--text-05)"
    />
  </svg>
);
export default SvgFileShare;
