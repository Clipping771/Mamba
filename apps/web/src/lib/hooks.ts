"use client";

import useSWR, { useSWRConfig, type SWRConfiguration } from "swr";

import { api, call, type Me } from "@/lib/api";

export function useMe() {
  return useSWR<Me>("me", () => call(api.GET("/auth/me")), {
    revalidateOnFocus: false,
    shouldRetryOnError: false,
  });
}

/** SWR wrapper: `key` null disables the request. */
export function useQuery<T>(key: unknown[] | null, fetcher: () => Promise<T>, config?: SWRConfiguration<T>) {
  return useSWR<T>(key, fetcher, { revalidateOnFocus: false, ...config });
}

/**
 * Revalidate cached queries whose key mentions any of `parts` (e.g. a case id, or "cases").
 * Needed before navigating: Cache Components keeps visited pages mounted (hidden), so they
 * would otherwise show stale data when you return to them.
 */
export function useInvalidate() {
  const { mutate } = useSWRConfig();
  return (...parts: string[]) =>
    mutate((key) => Array.isArray(key) && key.some((k) => parts.includes(String(k))));
}

export function isCasework(me: Me | undefined): boolean {
  return me?.role === "investigator" || me?.role === "reviewer";
}
