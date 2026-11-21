import { useEffect, useState, type FormEvent } from "react";
import { listen } from "@tauri-apps/api/event";
import { Button, InputPasswordTypeIn, InputTypeIn, Text } from "@opal/components";
import { SvgGoogle } from "@opal/logos";
import { Section } from "@opal/layouts";
import { mount } from "@/lib/mount";
import { ErrorText, Field, WindowFrame } from "@/lib/WindowFrame";
import {
  changeServer,
  errorMessage,
  getAuthMethods,
  getPrefs,
  login,
  signInWithSso,
  type AuthMethods,
} from "@/lib/ipc";

function Login() {
  const [server, setServer] = useState("");
  // Managed policy can lock the server; then there is no Change server.
  const [serverLocked, setServerLocked] = useState(true);
  const [methods, setMethods] = useState<AuthMethods | null>(null);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [waitingForSso, setWaitingForSso] = useState<"browser" | "window" | null>(null);
  const [startingSso, setStartingSso] = useState(false);
  // The browser sign-in in progress, so only its button offers to start again.
  const [browserProvider, setBrowserProvider] = useState<string | null>(null);
  // Set by any browser attempt, also one that could not open the browser.
  const [browserTried, setBrowserTried] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Set when the server's sign-in methods could not be read; the password form
  // stays available and "Try again" reads them again.
  const [discoveryError, setDiscoveryError] = useState<string | null>(null);

  function loadMethods() {
    setDiscoveryError(null);
    getAuthMethods()
      .then(setMethods)
      .catch((e) => {
        setMethods({ password: true, sso: [] });
        setDiscoveryError(errorMessage(e));
      });
  }

  useEffect(() => {
    void getPrefs().then((prefs) => {
      setServer(prefs.serverUrl ?? "");
      setServerLocked(prefs.serverLocked);
    });
    loadMethods();
    // An SSO sign-in that fails after it left this window reports back here.
    const unlisten = listen<string>("sso-failed", (event) => {
      setWaitingForSso(null);
      setError(event.payload);
    });
    return () => {
      void unlisten.then((stop) => stop());
    };
  }, []);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(email.trim(), password);
    } catch (e) {
      setError(errorMessage(e));
      setBusy(false);
    }
  }

  async function onSso(browser: boolean, provider: string | null = null) {
    setError(null);
    setStartingSso(true);
    if (browser) setBrowserTried(true);
    try {
      const waiting = await signInWithSso(browser, provider);
      setWaitingForSso(waiting);
      setBrowserProvider(waiting === "browser" ? provider : null);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setStartingSso(false);
    }
  }

  const showPassword = methods?.password ?? true;

  return (
    <WindowFrame title="Sign in to Onyx" subtitle={server}>
      <Section gap={4} alignItems="stretch" height="fit">
        {methods && methods.sso.length > 0 ? (
          <Section gap={2} alignItems="stretch" height="fit">
            {methods.sso.map((option) => (
              <Button
                key={option.provider ?? option.label}
                prominence="secondary"
                width="full"
                icon={option.google ? SvgGoogle : undefined}
                disabled={startingSso}
                onClick={() => void onSso(option.browser, option.provider)}
              >
                {waitingForSso === "browser" && option.browser && option.provider === browserProvider
                  ? "Start again in your browser"
                  : option.label}
              </Button>
            ))}
            {waitingForSso ? (
              <Text font="secondary-body" color="text-03">
                {waitingForSso === "browser"
                  ? "Continue signing in in your browser. Onyx opens when you are done."
                  : "Finish signing in in the window that opened. Onyx opens when you are done."}
              </Text>
            ) : null}
            {browserTried && waitingForSso !== "window" ? (
              // Servers older than the native-app callback bridge never send
              // the browser back to the app; their login page works in a window.
              <Button
                size="sm"
                prominence="tertiary"
                disabled={startingSso}
                onClick={() => void onSso(false)}
              >
                Not working? Sign in in an Onyx window instead
              </Button>
            ) : null}
          </Section>
        ) : null}
        {showPassword ? (
          <form onSubmit={onSubmit}>
            <Section gap={4} alignItems="stretch" height="fit">
              <Field label="Email" inputId="email">
                <InputTypeIn
                  id="email"
                  type="email"
                  autoFocus
                  autoComplete="username"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                />
              </Field>
              <Field label="Password" inputId="password">
                <InputPasswordTypeIn
                  id="password"
                  autoComplete="current-password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                />
              </Field>
              <Section
                flexDirection="row"
                justifyContent={serverLocked ? "end" : "between"}
                height="fit"
              >
                {serverLocked ? null : (
                  <Button prominence="tertiary" disabled={busy} onClick={() => void changeServer()}>
                    Change server
                  </Button>
                )}
                <Button type="submit" disabled={busy || email.trim() === "" || password === ""}>
                  {busy ? "Signing in…" : "Sign in"}
                </Button>
              </Section>
            </Section>
          </form>
        ) : serverLocked ? null : (
          <Section flexDirection="row" justifyContent="start" height="fit">
            <Button prominence="tertiary" disabled={busy} onClick={() => void changeServer()}>
              Change server
            </Button>
          </Section>
        )}
        {discoveryError ? (
          <Section flexDirection="row" gap={2} justifyContent="start" height="fit">
            <ErrorText message={`Could not load the sign-in options: ${discoveryError}`} />
            <Button size="sm" prominence="tertiary" onClick={loadMethods}>
              Try again
            </Button>
          </Section>
        ) : null}
        <ErrorText message={error} />
      </Section>
    </WindowFrame>
  );
}

mount(<Login />);
