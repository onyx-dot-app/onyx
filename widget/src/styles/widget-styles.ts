import { css } from "lit";

/**
 * Onyx Chat Widget - Component Styles
 * All styling for the main widget component
 */
export const widgetStyles = css`
  :host {
    display: block;
    font-family: var(--onyx-font-family);
  }

  .launcher {
    position: fixed;
    background: var(--onyx-background);
    bottom: 20px;
    right: 20px;
    width: 56px;
    height: 56px;
    border-radius: 50%;
    color: var(--onyx-text-light);
    border: none;
    cursor: pointer;
    box-shadow: var(--onyx-shadow);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: var(--onyx-z-launcher);
    transition:
      transform 200ms cubic-bezier(0.4, 0, 0.2, 1),
      box-shadow 200ms cubic-bezier(0.4, 0, 0.2, 1),
      background 200ms cubic-bezier(0.4, 0, 0.2, 1);
  }

  .launcher img {
    filter: drop-shadow(0px 1px 2px rgba(255, 255, 255, 0.3));
  }

  .launcher:hover {
    transform: translateY(-2px);
    background: var(--onyx-background-hover);
    box-shadow: 0px 4px 20px rgba(0, 0, 0, 0.2);
  }

  .launcher:active {
    transform: translateY(0px);
    box-shadow: var(--onyx-shadow);
  }

  .container {
    position: fixed;
    bottom: 20px;
    right: 20px;
    width: 400px;
    height: 600px;
    background: var(--onyx-background);
    border-radius: var(--onyx-radius-16);
    box-shadow: var(--onyx-shadow);
    display: flex;
    flex-direction: column;
    overflow: hidden;
    z-index: var(--onyx-z-widget);
    border: 1px solid var(--onyx-border);
    animation: fadeInSlideUp 300ms cubic-bezier(0.4, 0, 0.2, 1) forwards;
    opacity: 0;
    transform: translateY(20px);
  }

  @keyframes fadeInSlideUp {
    to {
      opacity: 1;
      transform: translateY(0);
    }
  }

  .container.inline {
    position: static;
    width: 100%;
    height: 500px;
    border-radius: var(--onyx-radius-08);
    animation: none;
    opacity: 1;
    transform: none;
  }

  .container.inline.compact {
    background: transparent;
    border: none;
    box-shadow: none;
    border-radius: var(--onyx-radius-16);
  }

  @media (max-width: 768px) {
    .container:not(.inline) {
      position: fixed;
      inset: 0;
      width: 100vw;
      height: 100vh;
      border-radius: 0;
      bottom: 0;
      right: 0;
    }
  }

  .header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: var(--onyx-space-md);
    background: var(--onyx-background);
    color: var(--onyx-text);
    border-bottom: 1px solid var(--onyx-border);
  }

  .header-left {
    display: flex;
    align-items: center;
    gap: var(--onyx-space-sm);
  }

  .header-right {
    display: flex;
    align-items: center;
    gap: var(--onyx-space-xs);
  }

  .avatar {
    width: 32px;
    height: 32px;
    border-radius: 50%;
    background: var(--onyx-background);
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 18px;
  }

  .header-title {
    font-weight: 600;
    font-size: var(--onyx-font-size-label);
    line-height: var(--onyx-line-height-label);
    color: var(--onyx-text);
  }

  .icon-button {
    background: none;
    border: none;
    color: var(--onyx-text);
    cursor: pointer;
    padding: var(--onyx-space-xs);
    border-radius: var(--onyx-radius-08);
    display: flex;
    align-items: center;
    justify-content: center;
    transition:
      background var(--onyx-transition-fast),
      color var(--onyx-transition-fast);
    font-size: 18px;
    width: 32px;
    height: 32px;
  }

  .icon-button:hover {
    background: var(--onyx-background);
    color: var(--onyx-text);
  }

  .messages {
    flex: 1;
    overflow-y: auto;
    padding: var(--onyx-space-md);
    display: flex;
    flex-direction: column;
    gap: var(--onyx-space-md);
    background: var(--onyx-background);
  }

  .message {
    display: flex;
    flex-direction: column;
    gap: var(--onyx-space-xs);
  }

  .message.user {
    align-items: flex-end;
  }

  .message.assistant {
    align-items: flex-start;
  }

  .message-bubble {
    max-width: 85%;
    padding: var(--onyx-space-sm) var(--onyx-space-md);
    border-radius: var(--onyx-radius-12);
    word-wrap: break-word;
    font-size: var(--onyx-font-size-main);
    line-height: var(--onyx-line-height-main);
  }

  .message.user .message-bubble {
    background: var(--onyx-user-message-bg);
    color: var(--onyx-text);
    border: 1px solid var(--onyx-border);
  }

  .message.assistant .message-bubble {
    background: var(--onyx-assistant-message-bg);
    color: var(--onyx-text);
    border: 1px solid var(--onyx-border);
  }

  /* Markdown styles */
  .message-bubble :first-child {
    margin-top: 0;
  }

  .message-bubble :last-child {
    margin-bottom: 0;
  }

  .message-bubble p {
    margin: 0.5em 0;
  }

  .message-bubble code {
    background: rgba(0, 0, 0, 0.08);
    padding: 2px 4px;
    border-radius: 3px;
    font-family: "Monaco", "Courier New", monospace;
    font-size: 0.9em;
  }

  .message-bubble pre {
    background: rgba(0, 0, 0, 0.08);
    padding: var(--onyx-space-sm);
    border-radius: var(--onyx-radius-sm);
    overflow-x: auto;
    margin: 0.5em 0;
  }

  .message-bubble pre code {
    background: none;
    padding: 0;
  }

  .message-bubble ul,
  .message-bubble ol {
    margin: 0.5em 0;
    padding-left: 1.5em;
  }

  .message-bubble li {
    margin: 0.25em 0;
  }

  .message-bubble a {
    color: var(--onyx-primary);
    text-decoration: underline;
  }

  .message-bubble a:hover {
    text-decoration: none;
  }

  .message-bubble h1,
  .message-bubble h2,
  .message-bubble h3,
  .message-bubble h4,
  .message-bubble h5,
  .message-bubble h6 {
    margin: 0.5em 0 0.25em 0;
    font-weight: 600;
  }

  .message-bubble h1 {
    font-size: 1.5em;
  }
  .message-bubble h2 {
    font-size: 1.3em;
  }
  .message-bubble h3 {
    font-size: 1.1em;
  }

  .message-bubble blockquote {
    border-left: 3px solid var(--onyx-border);
    margin: 0.5em 0;
    padding-left: var(--onyx-space-md);
    color: var(--onyx-text);
  }

  .message-bubble strong {
    font-weight: 600;
  }

  .message-bubble em {
    font-style: italic;
  }

  .message-bubble hr {
    border: none;
    border-top: 1px solid var(--onyx-border);
    margin: 0.5em 0;
  }

  .status-container {
    display: flex;
    align-items: center;
    gap: var(--onyx-space-sm);
  }

  .typing-indicator {
    display: flex;
    gap: 4px;
  }

  .typing-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: var(--onyx-text);
    animation: typing 1.4s infinite;
  }

  .typing-dot:nth-child(2) {
    animation-delay: 0.2s;
  }

  .typing-dot:nth-child(3) {
    animation-delay: 0.4s;
  }

  @keyframes typing {
    0%,
    60%,
    100% {
      opacity: 0.3;
      transform: translateY(0);
    }
    30% {
      opacity: 1;
      transform: translateY(-4px);
    }
  }

  .status-text {
    color: var(--onyx-text);
    font-size: var(--onyx-font-size-sm);
    font-style: italic;
  }

  .input-wrapper {
    border-top: 1px solid var(--onyx-border);
    background: var(--onyx-background);
  }

  .input-container {
    padding: var(--onyx-space-md) var(--onyx-space-md) 4px;
    display: flex;
    align-items: center;
    gap: var(--onyx-space-xs);
  }

  .input {
    flex: 1;
    min-width: 0;
    padding: var(--onyx-space-xs) var(--onyx-space-sm);
    border: 1px solid var(--onyx-primary);
    border-radius: var(--onyx-radius-08);
    font-size: var(--onyx-font-size-main);
    line-height: var(--onyx-line-height-main);
    outline: none;
    font-family: var(--onyx-font-family);
    background: var(--onyx-background);
    color: var(--onyx-text);
    transition:
      border-color var(--onyx-transition-fast),
      box-shadow var(--onyx-transition-fast);
    height: 36px;
  }

  .input:focus {
    border-color: var(--onyx-primary);
    box-shadow: 0 0 0 1px var(--onyx-background);
  }

  .powered-by {
    font-size: 10px;
    color: var(--onyx-text);
    opacity: 0.5;
    text-align: center;
    padding: 0 var(--onyx-space-md) var(--onyx-space-xs);
  }

  .powered-by a {
    color: var(--onyx-text);
    text-decoration: none;
    transition: opacity var(--onyx-transition-fast);
  }

  .powered-by a:hover {
    opacity: 0.8;
    text-decoration: underline;
  }

  .send-button {
    background: var(--onyx-primary);
    border: none;
    color: var(--onyx-text-light);
    cursor: pointer;
    padding: var(--onyx-space-sm);
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    transition:
      background var(--onyx-transition-fast),
      transform var(--onyx-transition-fast);
    flex-shrink: 0;
    width: 36px;
    height: 36px;
  }

  .send-button svg {
    width: 18px;
    height: 18px;
  }

  .send-button:hover:not(:disabled) {
    background: var(--onyx-primary-hover);
    transform: scale(1.05);
  }

  .send-button:active:not(:disabled) {
    transform: scale(0.95);
  }

  .send-button:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  .disclaimer {
    padding: var(--onyx-space-xs) var(--onyx-space-md);
    background: var(--onyx-background);
    color: var(--onyx-text);
    font-size: 11px;
    line-height: 1.3;
    text-align: center;
    border-bottom: 1px solid var(--onyx-border);
  }

  .error {
    padding: var(--onyx-space-md);
    background: var(--onyx-error-bg);
    color: var(--onyx-error-text);
    border-radius: var(--onyx-radius-08);
    margin: var(--onyx-space-md);
    font-size: var(--onyx-font-size-main);
  }

  /* Compact inline mode (no messages) */
  .container.compact {
    height: auto;
    min-height: unset;
    border: none;
    box-shadow: none;
    background: transparent;
  }

  .compact-input-container {
    display: flex;
    align-items: center;
    gap: var(--onyx-space-sm);
    padding: var(--onyx-space-md);
    background: var(--onyx-background);
    border-radius: var(--onyx-radius-16);
    border: 1px solid var(--onyx-border);
    box-shadow: var(--onyx-shadow);
    transition:
      border-color var(--onyx-transition-base),
      box-shadow var(--onyx-transition-base);
  }

  .compact-input-container:focus-within {
    border-color: var(--onyx-text);
    box-shadow:
      var(--onyx-shadow),
      0 0 0 3px var(--onyx-background);
  }

  .compact-avatar {
    width: 40px;
    height: 40px;
    border-radius: 50%;
    background: var(--onyx-background);
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
    color: var(--onyx-text-light);
    box-shadow: 0px 2px 8px rgba(0, 0, 0, 0.1);
  }

  .compact-input {
    flex: 1;
    min-width: 0;
    padding: var(--onyx-space-sm);
    border: none;
    font-size: var(--onyx-font-size-label);
    line-height: var(--onyx-line-height-label);
    outline: none;
    font-family: var(--onyx-font-family);
    background: transparent;
    color: var(--onyx-text);
    font-weight: 500;
  }

  .compact-input::placeholder {
    color: var(--onyx-text);
    font-weight: 400;
  }
`;
