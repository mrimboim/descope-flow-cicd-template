# Flow diff: `sign-up`

## Changes

- 🟢 **Added automated** `30` — Sign Up or In / Magic Link / Email
- 🟢 **Added screen** `31` — Magic Link Sent
- 🟢 **Added screen** `32` — Verified Successfully
- 🔴 **Removed screen** `15` — Verified Successfully
- 🔴 **Removed connector** `28` — Generic HTTP / GET
- 🟢 **New connection** Sign Up or In / Magic Link / Email ·success· → Magic Link Sent
- 🟢 **New connection** Magic Link Sent ·polling· → Verified Successfully
- 🟢 **New connection** Magic Link Sent ·resend· → Sign Up or In / Magic Link / Email
- 🔴 **Removed connection** Magic Link Sent ·polling· → Verified Successfully
- 🟡 **Error handling** Generic HTTP / GET · ConnectorFailed: automatic → —
- 🟡 **Error handling** Generic HTTP / GET · request_error: automatic → —

## Overview

![overview](00-overview.png)

## Changed regions

![cluster](10-cluster-0-magic-link-sent.png)

![cluster](10-cluster-1-generic-http-get.png)

![cluster](10-cluster-2-sign-up-or-in-magic-link-email.png)

## Screen changes

![screen](20-screen-added-magic-link-sent.png)

![screen](20-screen-added-verified-successfully.png)

![screen](20-screen-removed-verified-successfully.png)

