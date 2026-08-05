# Flow diff: `sign-up`

## Changes

- 🟢 **Added automated** `27` — Sign Up or In / Passkeys (WebAuthn)
- 🔴 **Removed screen** `18` — Verified Successfully
- 🔴 **Removed connector** `20` — APPPLE
- 🔴 **Removed connector** `22` — Generic HTTP / GET
- 🔴 **Removed connector** `23` — Get user
- 🟡 **Modified** `0` — Sign Up Screen (clientScripts, componentsConditions, componentsConnectors, connectorComponentProps, dynamicSelects, htmlTemplate, interactions, recoveryCodesData, screen)
- 🟢 **New connection** Sign Up Screen ·6KGtvzyiH_· → Sign Up or In / Passkeys (WebAuthn)
- 🟢 **New connection** Sign Up Screen ·keR6MsQTnS· → Sign Up / OAuth
- 🟢 **New connection** Sign Up or In / Passkeys (WebAuthn) ·success· → End
- 🔴 **Removed connection** Sign Up Screen ·Gjob4tKKNP· → Sign Up / OAuth
- 🔴 **Removed connection** Magic Link Sent ·polling· → Verified Successfully
- 🟡 **Error handling** APPPLE · ConnectorFailed: automatic → —
- 🟡 **Error handling** APPPLE · request_error: automatic → —
- 🟡 **Error handling** Generic HTTP / GET · ConnectorFailed: automatic → —
- 🟡 **Error handling** Generic HTTP / GET · request_error: automatic → —
- 🟡 **Error handling** Get user · ConnectorFailed: automatic → —
- 🟡 **Error handling** Get user · request_error: automatic → —

## Overview

![overview](00-overview.png)

## Changed regions

![cluster](10-cluster-0-sign-up-or-in-passkeys-webauthn.png)

![cluster](10-cluster-1-magic-link-sent.png)

![cluster](10-cluster-2-appple.png)

![cluster](10-cluster-3-generic-http-get.png)

![cluster](10-cluster-4-get-user.png)

## Screen changes

![screen](20-screen-sign-up-screen.png)

![screen](20-screen-removed-verified-successfully.png)

