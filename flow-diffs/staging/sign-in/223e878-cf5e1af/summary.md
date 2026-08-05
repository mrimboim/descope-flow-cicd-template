# Flow diff: `sign-in`

> Components version bump: **3.17.0 → 3.18.2** (0 default-prop changes suppressed as upgrade noise)

## Changes

- 🟢 **Added automated** `9` — Sign Up or In / Passkeys (WebAuthn)
- 🔴 **Removed screen** `7` — Verified Successfully
- 🟡 **Modified** `0` — Sign In Screen (htmlTemplate, interactions, screen)
- 🟡 **Modified** `8` — Sign In / OAuth (arguments, errorHandlingV2)
- 🟢 **New connection** Sign In Screen ·Cf2ZQ46VfU· → Sign In / OAuth
- 🟢 **New connection** Sign In Screen ·bL-cGpwCvI· → Sign Up or In / Passkeys (WebAuthn)
- 🟢 **New connection** Sign In / OAuth ·OAuthStartFailed· → End
- 🟢 **New connection** Sign Up or In / Passkeys (WebAuthn) ·success· → End
- 🔴 **Removed connection** Sign In Screen ·7GQnOKn5hG· → Sign In / OAuth
- 🔴 **Removed connection** Sign In Screen ·cf5EF1n0xK· → Sign In / OAuth
- 🔴 **Removed connection** Magic Link Sent ·polling· → Verified Successfully
- 🟣 Moved (position only, shown on connecting lines): Sign In Screen, Magic Link Sent, Sign In / OAuth, start
- 🟡 **Error handling** Sign In / OAuth · ActionErrorTenantDisabled: — → automatic
- 🟡 **Error handling** Sign In / OAuth · ActionErrorTenantRequiresSSO: — → automatic
- 🟡 **Error handling** Sign In / OAuth · OAuthCanceled: — → automatic
- 🟡 **Error handling** Sign In / OAuth · OAuthExchangeCodeFailed: — → automatic
- 🟡 **Error handling** Sign In / OAuth · OAuthExchangeNativeOAuthFailed: — → automatic
- 🟡 **Error handling** Sign In / OAuth · OAuthStartFailed: — → customWithError msg="Yes"

## Overview

![overview](00-overview.png)

## Changed regions

![cluster](10-cluster-0-sign-up-or-in-passkeys-webauthn.png)

## Screen changes

![screen](20-screen-sign-in-screen.png)

![screen](20-screen-removed-verified-successfully.png)

## Action changes

![action](40-action-sign-in-oauth.png)

