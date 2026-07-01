// postMessage source tag the OAuth callback popup sends back to its opener.
export const OAUTH_POPUP_MESSAGE_SOURCE = "onyx-external-app-oauth";

export interface OAuthPopupMessage {
  source: typeof OAUTH_POPUP_MESSAGE_SOURCE;
  externalAppId: number;
}
