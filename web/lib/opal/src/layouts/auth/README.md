# Auth Layouts

**Import:** `import { AuthLayouts } from "@opal/layouts";`

Namespaced layout primitives for authentication pages. Provides a full-screen centering shell
and a branded card with logo, title, description, form slots, and an optional bottom prompt.

## Components

### Root

Full-screen centering wrapper. Wrap every auth page with this.

No props — accepts `children` only.

### Card

The main auth card. Renders an icon above a heading, optional description, card content, and
an optional bottom prompt rendered outside/below the card border.

| Prop | Type | Default | Description |
|---|---|---|---|
| `icon` | `IconFunctionComponent` | **(required)** | Logo/icon rendered above the card heading |
| `title` | `string \| RichStr` | **(required)** | Card heading |
| `description` | `string \| RichStr` | — | Subtitle below the heading |
| `children` | `ReactNode` | — | Card body (form, buttons, separators) |
| `bottomPrompt` | `string \| RichStr` | — | Text/link below the card (e.g. "Already have an account?") |

### OrSeparator

A centered "or" label flanked by two divider lines. Use between an SSO button and an
email/password form.

No props.

### Fields

Flex-column container for form inputs with a consistent `0.75rem` gap between fields.

| Prop | Type | Default | Description |
|---|---|---|---|
| `children` | `ReactNode` | — | Input field components |

### Submit

Full-width submit button. Thin wrapper around `Button` with `type="submit"` and `width="full"`.

| Prop | Type | Default | Description |
|---|---|---|---|
| `label` | `SubmitLabel` | **(required)** | Button label key (`"sign-in"`, `"sign-up"`, etc.) |
| `isSubmitting` | `boolean` | — | Disables + shows spinner while submitting |
| `isValid` | `boolean` | — | When provided, disables if `false` |
| `dirty` | `boolean` | — | When provided, disables if `false` |

## Usage Example

```tsx
import { AuthLayouts } from "@opal/layouts";
import { markdown } from "@opal/utils";
import { getAppLogo } from "@/lib/app/utils";

<AuthLayouts.Root>
  <AuthLayouts.Card
    icon={getAppLogo(logoSrc)}
    title="Welcome back"
    description="Sign in to your account"
    bottomPrompt={markdown("Don't have an account? [Create an Account](/auth/signup)")}
  >
    <SignInButton authorizeUrl={authUrl} authType={AuthType.CLOUD} />
    <AuthLayouts.OrSeparator />
    <Formik ...>
      {({ isSubmitting, isValid, dirty }) => (
        <Form className="flex flex-col gap-6">
          <AuthLayouts.Fields>
            <TextFormField name="email" label="Email" type="email" />
            <TextFormField name="password" label="Password" type="password" />
          </AuthLayouts.Fields>
          <AuthLayouts.Submit label="submit" isSubmitting={isSubmitting} isValid={isValid} dirty={dirty} />
        </Form>
      )}
    </Formik>
  </AuthLayouts.Card>
</AuthLayouts.Root>
```
