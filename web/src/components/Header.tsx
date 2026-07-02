import type { FC } from "react";
import { Link } from "react-router-dom";
import { useTheme } from "../hooks/useTheme";
import { DEMO_MODE } from "../lib/demoModeGuard";
import styles from "./Header.module.css";

export const Header: FC = () => {
  const { theme, toggle } = useTheme();

  return (
    <header className={styles.header}>
      <Link to="/" className={styles.logo}>
        <span className={styles.logoIcon}>⚡</span>
        Llull
      </Link>
      {DEMO_MODE && (
        <span className={styles.demoBadge} title="This instance is read-only — no changes are saved">
          🔒 Demo — read only
        </span>
      )}
      <div className={styles.actions}>
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
