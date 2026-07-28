import type { FC } from "react";

interface ErrorMessageProps {
  error: unknown;
  fallback?: string;
}

export const ErrorMessage: FC<ErrorMessageProps> = ({
  error,
  fallback = "An error occurred",
}) => {
  const message = error instanceof Error ? error.message : fallback;
  return (
    <div
      style={{
        padding: "1rem",
        background: "rgba(239,68,68,0.1)",
        border: "1px solid var(--danger)",
        borderRadius: "8px",
        color: "var(--danger)",
        fontSize: "0.875rem",
      }}
    >
      ⚠️ {message}
    </div>
  );
};
