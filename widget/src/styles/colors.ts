import { css } from "lit";

export const colors = css`
  :host {
    /* Main Colors - Configurable via env vars */
    --onyx-primary: #1c1c1c; /* Default primary color (buttons, accents) */
    --onyx-primary-hover: #000000; /* Darker on hover */
    --onyx-background: #e9e9e9; /* Default background color */
    --onyx-background-hover: #d9d9d9; /* Background color on hover */
    --onyx-text: #000000bf; /* Default text color (75% opacity) */

    /* Derived Colors */
    --onyx-text-light: #ffffff; /* White text for dark backgrounds */
    --onyx-border: #00000033; /* Border color (20% opacity) */
    --onyx-shadow: 0px 2px 12px rgba(0, 0, 0, 0.1);

    /* Error Colors */
    --onyx-error-bg: #fee;
    --onyx-error-text: #c00;
  }
`;
