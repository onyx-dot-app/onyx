import type { IconProps } from "@opal/types";
const SvgLoader = ({ size, ...props }: IconProps) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 16 16"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    stroke="currentColor"
    {...props}
  >
    <g clipPath="url(#clip0_4368_92944)">
      <g clipPath="url(#clip1_4368_92944)">
        <path
          d="M8.00001 14.6667C4.31812 14.6667 1.33335 11.6819 1.33335 8"
          strokeWidth={1.5}
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        <path
          d="M8.00001 14.6666C4.31812 14.6666 1.33335 11.6819 1.33335 7.99997"
          strokeWidth={1.5}
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        <path
          d="M14.6667 8C14.6667 11.6819 11.6819 14.6667 7.99999 14.6667"
          strokeWidth={1.5}
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        <path
          d="M8.00002 1.33336C11.6819 1.33336 14.6667 4.31813 14.6667 8.00003"
          strokeWidth={1.5}
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </g>
      <path
        d="M8.00003 1.33333C9.84098 1.33333 11.5076 2.07952 12.7141 3.28595"
        strokeWidth={1.5}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </g>
  </svg>
);
export default SvgLoader;
