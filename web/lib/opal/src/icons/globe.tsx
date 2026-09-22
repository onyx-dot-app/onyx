import type { IconProps } from "@opal/types";
const SvgGlobe = ({ size, ...props }: IconProps) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 16 16"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    stroke="currentColor"
    {...props}
  >
    <g clipPath="url(#clip0_16_2601)">
      <path
        d="M14.6667 7.99998C14.6667 11.6819 11.6819 14.6666 7.99999 14.6666M14.6667 7.99998C14.6667 4.31808 11.6819 1.33331 7.99999 1.33331M14.6667 7.99998H1.33333M7.99999 14.6666C4.3181 14.6666 1.33333 11.6819 1.33333 7.99998M7.99999 14.6666C9.66751 12.8411 10.6152 10.472 10.6667 7.99998C10.6152 5.528 9.66751 3.15888 7.99999 1.33331M7.99999 14.6666C6.33247 12.8411 5.38483 10.472 5.33333 7.99998C5.38483 5.528 6.33247 3.15888 7.99999 1.33331M1.33333 7.99998C1.33333 4.31808 4.3181 1.33331 7.99999 1.33331"
        strokeWidth={1.5}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </g>
  </svg>
);
export default SvgGlobe;
