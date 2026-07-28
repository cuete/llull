import { useHealth } from "./useHealth";

/**
 * Whether the server is running in read-only mode (blocks create/update actions).
 * Polled via /health so a server-side flag flip is picked up without a page reload.
 */
export function useReadOnly(): boolean {
  return useHealth()?.read_only ?? false;
}
