import { useQuery } from "@tanstack/react-query";
import { getHealth } from "../lib/api";
import type { Health } from "../lib/types";

/** Shared /health poll — backs useReadOnly and auth gating. */
export function useHealth(): Health | undefined {
  const { data } = useQuery({
    queryKey: ["health"],
    queryFn: getHealth,
    staleTime: 30_000,
    refetchInterval: 30_000,
  });

  return data;
}
