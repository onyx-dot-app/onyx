import { useEffect, useState, type FormEvent } from "react";
import { Button, InputPasswordTypeIn, InputTypeIn } from "@opal/components";
import { Section } from "@opal/layouts";
import { mount } from "@/lib/mount";
import { ErrorText, Field, WindowFrame } from "@/lib/WindowFrame";
import { changeServer, errorMessage, getPrefs, login } from "@/lib/ipc";

function Login() {
  const [server, setServer] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void getPrefs().then((prefs) => setServer(prefs.serverUrl ?? ""));
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

  return (
    <WindowFrame title="Sign in to Onyx" subtitle={server}>
      <Section gap={4} alignItems="stretch" height="fit">
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
            <Section flexDirection="row" justifyContent="between" height="fit">
              <Button prominence="tertiary" disabled={busy} onClick={() => void changeServer()}>
                Change server
              </Button>
              <Button type="submit" disabled={busy || email.trim() === "" || password === ""}>
                {busy ? "Signing in…" : "Sign in"}
              </Button>
            </Section>
          </Section>
        </form>
        <ErrorText message={error} />
      </Section>
    </WindowFrame>
  );
}

mount(<Login />);
