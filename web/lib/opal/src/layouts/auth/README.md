# Auth Layouts

**Import:** `import { AuthLayouts } from "@opal/layouts";`

Namespaced layout primitives for authentication pages. Provides a full-screen centering shell
and a branded card with logo, title, description, form slots, and an optional bottom prompt.

## Components

### Root

Full-screen centering wrapper. Wrap every auth page with this.

No props — accepts `children` only.

### Card

The main auth card. Renders the Onyx logo (or a custom logo), a heading, an optional
description, card content, and a bottom prompt rendered outside/below the card border.

| Prop | Type | Default | Description |
|---|---|---|---|
| `title` | `string \| RichStr` | **(required)** | Card heading |
| `description` | `string \| RichStr` | — | Subtitle below the heading |
| `children` | `ReactNode` | — | Card body (form, buttons, separators) |
| `bottomPrompt` | `string \| RichStr` | — | Text/link below the card (e.g. "Already have an account?") |
| `logoSrc` | `string \| null` | — | Custom logo URL; falls back to the Onyx logo |

### OrSeparator

A centered "or" label flanked by two divider lines. Use between an SSO button and an
email/password form.

No props.

### FormFields

Flex-column container for form inputs with a consistent `1rem` gap between fields.

| Prop | Type | Default | Description |
|---|---|---|---|
| `children` | `ReactNode` | — | Input field components |

### Submit

Full-width submit button. Thin wrapper around `Button` with `type="submit"` and `width="full"`.

| Prop | Type | Default | Description |
|---|---|---|---|
| `children` | `string` | **(required)** | Button label |
| `disabled` | `boolean` | `false` | Disabled state — pass `isSubmitting` from Formik |

## Usage Example

```tsx
import { AuthLayouts } from "@opal/layouts";
import { markdown } from "@opal/utils";

<AuthLayouts.Root>
  <AuthLayouts.Card
    title="Welcome to Onyx"
    description="Your open source AI platform for work"
    bottomPrompt={markdown("New to Onyx? [Create an Account](/auth/signup)")}
    logoSrc={logoUrl}
  >
    <SignInButton authorizeUrl={authUrl} authType={AuthType.CLOUD} />
    <AuthLayouts.OrSeparator />
    <Formik ...>
      {({ isSubmitting }) => (
        <Form className="flex flex-col gap-6">
          <AuthLayouts.FormFields>
            <TextFormField name="email" label="Email" type="email" />
            <TextFormField name="password" label="Password" type="password" />
          </AuthLayouts.FormFields>
          <AuthLayouts.Submit disabled={isSubmitting}>Sign in</AuthLayouts.Submit>
        </Form>
      )}
    </Formik>
  </AuthLayouts.Card>
</AuthLayouts.Root>
```
