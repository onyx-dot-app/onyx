import { css } from "lit";

export const colors = css`
  :host {
    /* Base Colors - Aligned with web/src/app/css/colors.css */
    --grey-100: #000000;
    --grey-10: #e6e6e6;
    --grey-00: #ffffff;
    --alpha-grey-100-75: #000000bf;
    --alpha-grey-100-20: #00000033;

    /* Onyx Brand Colors */
    --onyx-ink-100: #000000;
    --onyx-ink-95: #1c1c1c;

    /* Theme / Primary - Configurable via env vars */
    --theme-primary-06: var(--onyx-ink-100);
    --theme-primary-05: var(--onyx-ink-95);

    /* Background / Neutral */
    --background-neutral-00: var(--grey-00);
    --background-neutral-03: var(--grey-10);

    /* Text */
    --text-04: var(--alpha-grey-100-75);
    --text-light-05: var(--grey-00);

    /* Border */
    --border-01: var(--alpha-grey-100-20);

    /* Shadow */
    --shadow-02: 0px 2px 12px rgba(0, 0, 0, 0.1);

    /* Status / Error */
    --status-error-01: #fee;
    --status-error-05: #c00;
  }
`;
