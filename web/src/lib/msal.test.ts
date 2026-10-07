// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from "vitest";

const acquireTokenSilent = vi.fn();
const getActiveAccount = vi.fn();
const getAllAccounts = vi.fn();
const setActiveAccount = vi.fn();

vi.mock("@azure/msal-browser", () => ({
  PublicClientApplication: class {
    acquireTokenSilent = acquireTokenSilent;
    getActiveAccount = getActiveAccount;
    getAllAccounts = getAllAccounts;
    setActiveAccount = setActiveAccount;
  },
}));

const account = { homeAccountId: "home", username: "user@example.com" };
const inAnHour = Math.floor(Date.now() / 1000) + 3600;
const anHourAgo = Math.floor(Date.now() / 1000) - 3600;

async function loadMsal() {
  vi.resetModules();
  vi.stubEnv("VITE_MSAL_CLIENT_ID", "client-id");
  return import("./msal");
}

describe("getIdToken", () => {
  beforeEach(() => {
    acquireTokenSilent.mockReset();
    getActiveAccount.mockReset().mockReturnValue(account);
    getAllAccounts.mockReset().mockReturnValue([account]);
    setActiveAccount.mockReset();
  });

  it("returns a valid token without flagging the session", async () => {
    const msal = await loadMsal();
    acquireTokenSilent.mockResolvedValue({ idToken: "good", idTokenClaims: { exp: inAnHour } });

    expect(await msal.getIdToken()).toBe("good");
    expect(msal.isSessionExpired()).toBe(false);
  });

  it("uses a remembered account when none is active", async () => {
    const msal = await loadMsal();
    getActiveAccount.mockReturnValue(null);
    acquireTokenSilent.mockResolvedValue({ idToken: "good", idTokenClaims: { exp: inAnHour } });

    expect(await msal.getIdToken()).toBe("good");
    expect(setActiveAccount).toHaveBeenCalledWith(account);
  });

  it("forces a refresh when the cached ID token is past its expiry", async () => {
    const msal = await loadMsal();
    acquireTokenSilent
      .mockResolvedValueOnce({ idToken: "stale", idTokenClaims: { exp: anHourAgo } })
      .mockResolvedValueOnce({ idToken: "fresh", idTokenClaims: { exp: inAnHour } });

    expect(await msal.getIdToken()).toBe("fresh");
    expect(acquireTokenSilent).toHaveBeenLastCalledWith(
      expect.objectContaining({ forceRefresh: true }),
    );
    expect(msal.isSessionExpired()).toBe(false);
  });

  it("flags the session as expired when it cannot be renewed silently", async () => {
    const msal = await loadMsal();
    const listener = vi.fn();
    msal.subscribeSessionExpired(listener);
    acquireTokenSilent.mockRejectedValue(new Error("interaction_required"));

    expect(await msal.getIdToken()).toBeNull();
    expect(msal.isSessionExpired()).toBe(true);
    expect(listener).toHaveBeenCalledTimes(1);
  });

  it("does not flag a visitor who has never signed in", async () => {
    const msal = await loadMsal();
    getActiveAccount.mockReturnValue(null);
    getAllAccounts.mockReturnValue([]);

    expect(await msal.getIdToken()).toBeNull();
    expect(msal.isSessionExpired()).toBe(false);
  });
});
