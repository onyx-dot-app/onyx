import type { IconProps } from "@opal/types";

const SvgDownloadCloud = ({ size, ...props }: IconProps) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 16 16"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    stroke="currentColor"
    {...props}
  >
    <g clipPath="url(#clip0_download_cloud)">
      <path
        d="M5.33333 11.3333L8 14M8 14L10.6667 11.3333M8 14L8 8M13.6492 11.6045C14.2021 11.2157 14.6168 10.6608 14.833 10.0204C15.0492 9.37991 15.0556 8.68724 14.8515 8.04286C14.6473 7.39848 14.2431 6.83591 13.6976 6.43681C13.152 6.03771 12.4935 5.82283 11.8176 5.82336H11.0162C10.8249 5.0779 10.467 4.38554 9.96944 3.79841C9.47186 3.21129 8.84757 2.74469 8.14357 2.43375C7.43956 2.12281 6.67419 1.97563 5.90508 2.00329C5.13596 2.03095 4.38314 2.23272 3.70329 2.59343C3.02344 2.95414 2.43428 3.46437 1.98016 4.08572C1.52604 4.70707 1.21879 5.42335 1.08155 6.18063C0.94431 6.9379 0.980651 7.71645 1.18784 8.45765C1.39502 9.19885 1.76766 9.88339 2.27769 10.4597"
        stroke-width="1.5"
        stroke-linecap="round"
        stroke-linejoin="round"
      />
    </g>
    <defs>
      <clipPath id="clip0_download_cloud">
        <rect width={16} height={16} fill="white" />
      </clipPath>
    </defs>
  </svg>
);

export default SvgDownloadCloud;
