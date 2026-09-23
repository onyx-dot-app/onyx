# Salesforce External Client App package

This Salesforce DX project defines the managed package for the Onyx Cloud
External Client App (ECA). Salesforce administrators install the package before
they authorize Onyx.

The permanent Dev Hub owns the package and its global OAuth configuration.
Subscriber organizations install the ECA metadata and apply their own access
policies.

## Security boundary

The files in this directory contain package metadata and public Salesforce
identifiers. They do not contain credentials.

Never commit:

- `ExtlClntAppGlobalOauthSettings` metadata
- The ECA consumer key or consumer secret
- Salesforce access or refresh tokens
- Salesforce CLI authentication data from `.sf/` or `.sfdx/`

Store the consumer key and secret in the Onyx Cloud secret manager. Do not
generate local consumer credentials in subscriber organizations. Local
credentials disconnect the installed app from the OAuth configuration that
Onyx manages.

## Prerequisites

Before you create a package version:

1. Authenticate the permanent Dev Hub with Salesforce CLI.
2. Confirm that the `OnyxAI` namespace is linked to the Dev Hub.
3. Confirm that the **Onyx Cloud** ECA has **Packaged** distribution.
4. Update the ECA in the Dev Hub before you retrieve metadata.

Use a local alias for the Dev Hub:

```bash
sf org login web \
  --alias <dev-hub-alias> \
  --set-default-dev-hub \
  --instance-url https://<dev-hub-my-domain>
```

## Update the package source

Retrieve only the packageable ECA metadata:

```bash
cd integrations/salesforce/eca

sf project retrieve start \
  --manifest manifest/package.xml \
  --target-org <dev-hub-alias>
```

Review the diff before you commit it. Do not add global OAuth settings.

Update `versionName` in `sfdx-project.json` for the new version. Keep
`versionNumber` set to `0.1.0.NEXT` until the package needs a new release line.

## Create and test a package version

Create a validated package version:

```bash
sf package version create \
  --package "Onyx Salesforce OAuth" \
  --installation-key-bypass \
  --code-coverage \
  --wait 30 \
  --target-dev-hub <dev-hub-alias>
```

Always use `--code-coverage`. Salesforce requires a stored coverage result for
promotion, including packages without Apex code. Do not use
`--skip-validation` for a version that you plan to release.

The command adds the new `04t` version ID to `packageAliases`. Commit that
change.

Install the new version into a scratch org that does not use the publisher
namespace:

```bash
sf org create scratch \
  --target-dev-hub <dev-hub-alias> \
  --alias onyx-eca-subscriber-test \
  --edition developer \
  --duration-days 7 \
  --no-namespace

sf package install \
  --package <version-04t-id> \
  --target-org onyx-eca-subscriber-test \
  --wait 20 \
  --publish-wait 20
```

In the scratch org:

1. Configure the ECA permitted-user policy.
2. Authorize Onyx through Salesforce.
3. Create a connector and complete an indexing run.
4. Confirm that a later run can refresh the OAuth token.

## Release a package version

Inspect the version before promotion:

```bash
sf package version report \
  --package <version-04t-id> \
  --target-dev-hub <dev-hub-alias>
```

Confirm that validation was not skipped and code coverage passed. Promotion is
irreversible:

```bash
sf package version promote \
  --package <version-04t-id> \
  --target-dev-hub <dev-hub-alias>
```

The current released version is `0.1.0.4`:

- Production and Developer Edition:
  `https://login.salesforce.com/packaging/installPackage.apexp?p0=04tbm000000jYfxAAE`
- Sandbox:
  `https://test.salesforce.com/packaging/installPackage.apexp?p0=04tbm000000jYfxAAE`

After promotion, update the public Salesforce connector documentation with the
released version ID.

Released versions are immutable. Create a new version for each metadata change.
After the first release, keep `ancestorVersion` set to `HIGHEST` in
`sfdx-project.json`. This creates the ancestry that Salesforce requires for
subscriber upgrades.
