import { QueryClient, useMutation, useQuery } from "@tanstack/react-query";
import { callWS } from "./hass";
import type { ActivityEntry, Config, Conflict, Interval, Meta, Plan, Status } from "./types";

export const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 30_000, refetchOnWindowFocus: false, retry: 1 } },
});

export const useConfig = () =>
  useQuery({ queryKey: ["config"], queryFn: () => callWS<{ config: Config; meta: Meta }>({ type: "shabbot/config" }) });

export const usePlan = (start: string, end: string, enabled = true) =>
  useQuery({
    queryKey: ["plan", start, end],
    queryFn: () => callWS<Plan>({ type: "shabbot/plan", start, end }),
    enabled,
    placeholderData: (prev) => prev,
  });

export const useTimeline = (start: string, end: string) =>
  useQuery({
    queryKey: ["timeline", start, end],
    queryFn: () => callWS<Record<string, Interval[]>>({ type: "shabbot/timeline", start, end }),
  });

export const useStatus = () =>
  useQuery({ queryKey: ["status"], queryFn: () => callWS<Status>({ type: "shabbot/status" }), refetchInterval: 30_000 });

export const useActivity = () =>
  useQuery({ queryKey: ["activity"], queryFn: () => callWS<ActivityEntry[]>({ type: "shabbot/activity", limit: 500 }) });

/** Rows anywhere in the config that would fight over one device in the next year. */
export const useConflicts = () =>
  useQuery({ queryKey: ["conflicts"], queryFn: () => callWS<Conflict[]>({ type: "shabbot/conflicts" }) });

/** Any write: send it, then refresh everything derived from config. */
export function useSave<V extends Record<string, unknown>>(type: string) {
  return useMutation({
    mutationFn: (vars: V) => callWS<unknown>({ type, ...vars }),
    onSuccess: () => invalidateAll(),
  });
}

export function invalidateAll(): void {
  for (const key of ["config", "plan", "timeline", "status", "conflicts"]) queryClient.invalidateQueries({ queryKey: [key] });
}

export function errorMessage(err: unknown): string {
  if (!err) return "";
  if (typeof err === "object" && err && "message" in err) return String((err as { message: unknown }).message);
  return String(err);
}
