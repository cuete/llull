import { useIsAuthenticated } from "@azure/msal-react";
import type { FC, ReactNode } from "react";
import { useState, useSyncExternalStore } from "react";
import { useHealth } from "../hooks/useHealth";
import {
  isSessionExpired,
  loginWithMicrosoft,
  msalEnabled,
  subscribeSessionExpired,
} from "../lib/msal";
import styles from "./AuthGate.module.css";

interface AuthGateProps {
  children: ReactNode;
}

/**
 * Blocks the app behind Microsoft sign-in when the backend has AUTH_ENABLED=true.
 * Authentication only — any signed-in Microsoft account is let through, no
 * per-user authorization checks.
 */
export const AuthGate: FC<AuthGateProps> = ({ children }) => {
  const health = useHealth();
  const isAuthenticated = useIsAuthenticated();
  // A remembered account whose session can't be renewed must sign in again
  const sessionExpired = useSyncExternalStore(subscribeSessionExpired, isSessionExpired);
  const [error, setError] = useState<string | null>(null);
  const [signingIn, setSigningIn] = useState(false);

  // Health not loaded yet, or the server doesn't require auth — render normally.
  if (!health?.auth_enabled || !msalEnabled) return <>{children}</>;

  if (isAuthenticated && !sessionExpired) return <>{children}</>;

  const handleSignIn = () => {
    setError(null);
    setSigningIn(true);
    loginWithMicrosoft()
      .catch((err: unknown) => {
        console.error("Microsoft sign-in failed:", err);
        setError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => setSigningIn(false));
  };

  return (
    <div className={styles.overlay}>
      <div className={styles.card}>
        <span className={styles.icon}>⚡</span>
        <h1 className={styles.title}>Llull</h1>
        <p className={styles.subtitle}>
          {sessionExpired
            ? "Your session has expired. Sign in again to continue"
            : "Sign in with your Microsoft account to continue"}
        </p>
        <button className="btn btn-primary" onClick={handleSignIn} disabled={signingIn}>
          {signingIn ? "Signing in…" : "Sign in with Microsoft"}
        </button>
        {error && (
          <p style={{ color: "var(--danger, #ef4444)", fontSize: "0.85rem", marginTop: "1rem" }}>
            {error}
          </p>
        )}
      </div>
    </div>
  );
};
