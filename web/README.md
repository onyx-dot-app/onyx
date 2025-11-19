<!-- ONYX_METADATA={"link": "https://github.com/onyx-dot-app/onyx/blob/main/web/README.md"} -->

This is a [Next.js](https://nextjs.org/) project bootstrapped with [`create-next-app`](https://github.com/vercel/next.js/tree/canary/packages/create-next-app).

## Getting Started

Install node / npm: https://docs.npmjs.com/downloading-and-installing-node-js-and-npm
Install all dependencies: `npm i`

Then, run the development server:

```bash
npm run dev
# or
yarn dev
# or
pnpm dev
```

Open [http://localhost:3000](http://localhost:3000) with your browser to see the result.

_Note:_ if you are having problems accessing the ^, try setting the `WEB_DOMAIN` env variable to
`http://127.0.0.1:3000` and accessing it there.

## Testing

This testing process will reset your application into a clean state.
Don't run these tests if you don't want to do this!

Bring up the entire application.

0. Install playwright dependencies
```cd web
npx playwright install
```

1. Reset the instance

```cd backend
export PYTEST_IGNORE_SKIP=true
pytest -s tests/integration/tests/playwright/test_playwright.py
```

If you don't want to reset your local instance, you can still run playwright tests
with SKIP_AUTH=true. This is convenient but slightly different from what happens
in CI so tests might pass locally and fail in CI.

```cd web
SKIP_AUTH=true npx playwright test create_and_edit_assistant.spec.ts --project=no-auth
```

2. Run playwright

```
cd web
npx playwright test
```

To run a single test:

```
npx playwright test landing-page.spec.ts
```

If running locally, interactive options can help you see exactly what is happening in
the test.

```
npx playwright test --ui
npx playwright test --headed
```

3. Inspect results

By default, playwright.config.ts is configured to output the results to:

```
web/test-results
```

4. Upload results to Chromatic (Optional)

This step would normally not be run by third party developers, but first party devs
may use this for local troubleshooting and testing.

```
cd web
npx chromatic --playwright --project-token={your token here}
```
