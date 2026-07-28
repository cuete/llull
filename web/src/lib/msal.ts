import { PublicClientApplication } from "@azure/msal-browser";

// Personal Microsoft accounts only (MSA) — "consumers" is the JWKS/authority alias
// the backend also uses in AAD_TENANT_ID. Matches AAD_CLIENT_ID on the backend.
const CLIENT_ID = import.meta.env.VITE_MSAL_CLIENT_ID ?? "";

export const msalEnabled = CLIENT_ID.length > 0;

// Always construct the instance (even with an empty clientId) so MsalProvider can
// wrap the app unconditionally — @azure/msal-react hooks require a provider in the
// tree regardless of whether auth is actually configured. Actual usage below is
// gated behind msalEnabled.
export const msalInstance = new PublicClientApplication({
  auth: {
    clientId: CLIENT_ID,
    authority: "https://login.microsoftonline.com/consumers",
    // Redirect flow, not popup: login.microsoftonline.com sends a strict
    // Cross-Origin-Opener-Policy header that severs the opener's ability to read
    // the popup's location once it navigates through Microsoft's domain, even
    // after it returns to our origin — a known MSAL/Chrome popup-flow issue.
    // Redirect flow avoids cross-window polling entirely (same window navigates
    // away and back), so the app itself is the redirect target again.
    redirectUri: window.location.origin,
  },
  cache: {
    cacheLocation: "localStorage",
  },
});

// Requesting only openid+profile keeps this authentication-only (no API scopes /
// authorization). The backend validates the ID token (aud === client id), not an
// access token, since there is no exposed API scope to request one against.
const LOGIN_SCOPES = ["openid", "profile"];

/** Call once at app startup, after msalInstance.initialize(), before relying on auth state. */
export async function processRedirectResponse(): Promise<void> {
  if (!msalEnabled) return;
  const result = await msalInstance.handleRedirectPromise();
  if (result?.account) {
    msalInstance.setActiveAccount(result.account);
  }
}

export async function loginWithMicrosoft(): Promise<void> {
  if (!msalEnabled) return;
  await msalInstance.loginRedirect({ scopes: LOGIN_SCOPES });
}

export function logoutFromMicrosoft(): void {
  if (!msalEnabled) return;
  const account = msalInstance.getActiveAccount();
  void msalInstance.logoutRedirect({ account });
}

/** ID token for the active account, silently refreshing if needed. Null if signed out. */
export async function getIdToken(): Promise<string | null> {
  if (!msalEnabled) return null;
  const account = msalInstance.getActiveAccount();
  if (!account) return null;
  try {
    const result = await msalInstance.acquireTokenSilent({ scopes: LOGIN_SCOPES, account });
    return result.idToken;
  } catch {
    return null;
  }
}
