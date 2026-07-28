import { useIsAuthenticated, useMsal } from "@azure/msal-react";
import type { FC } from "react";
import { Link } from "react-router-dom";
import { useHealth } from "../hooks/useHealth";
import { useReadOnly } from "../hooks/useReadOnly";
import { useTheme } from "../hooks/useTheme";
import { logoutFromMicrosoft, msalEnabled } from "../lib/msal";
import styles from "./Header.module.css";

export const Header: FC = () => {
  const { theme, toggle } = useTheme();
  const readOnly = useReadOnly();
  const health = useHealth();
  const isAuthenticated = useIsAuthenticated();
  const { accounts } = useMsal();
  const showAccount = msalEnabled && health?.auth_enabled && isAuthenticated;

  return (
    <header className={styles.header}>
      <Link to="/" className={styles.logo}>
        <span className={styles.logoIcon}>⚡</span>
        Llull
      </Link>
      <div className={styles.actions}>
        {readOnly && (
          <span className={styles.readOnlyBadge} title="Server is in read-only mode: exploring only, no create/update actions">
            🔒 Read-only
          </span>
        )}
        {showAccount && (
          <button
            className={styles.settingsLink}
            onClick={logoutFromMicrosoft}
            title="Sign out"
          >
            👤 {accounts[0]?.username ?? "Signed in"} · Sign out
          </button>
        )}
        <button
          className={styles.themeBtn}
          onClick={toggle}
          title={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
        >
          {theme === "dark" ? "☀️" : "🌙"}
        </button>
        <Link to="/settings" className={styles.settingsLink}>
          ⚙️ Settings
        </Link>
      </div>
    </header>
  );
};
