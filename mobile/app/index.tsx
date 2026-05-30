import { Redirect } from "expo-router";

// Entry route. For now it sends users straight into the chat surface.
//
// Auth gating (see doc 07) will replace this: the AuthProvider decides whether
// to redirect into the (auth) group (logged out) or the (app) group (has a PAT).
export default function Index() {
  // typedRoutes is enabled (app.json experiments) but the .expo/types route
  // map isn't generated offline, so the Href union is unknown here — cast to
  // keep the typecheck green. Remove the cast once route types are generated.
  return <Redirect href={"/(app)/(chat)" as never} />;
}
