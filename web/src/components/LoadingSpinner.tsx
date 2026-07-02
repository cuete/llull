import type { FC } from "react";

interface LoadingSpinnerProps {
  size?: number;
  label?: string;
}

export const LoadingSpinner: FC<LoadingSpinnerProps> = ({
  size = 20,
  label = "Loading…",
}) => {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", padding: "1rem" }}>
      <div
        className="spinner"
        style={{ width: size, height: size }}
        role="status"
        aria-label={label}
      />
      <span style={{ color: "var(--text-secondary)", fontSize: "0.875rem" }}>{label}</span>
    </div>
  );
};
