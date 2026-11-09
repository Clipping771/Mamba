import "server-only";

import type { NextResponse } from "next/server";

/** Tokens never reach browser JavaScript: they live in httpOnly, SameSite=strict cookies. */
export const ACCESS_COOKIE = "bm_access";
export const REFRESH_COOKIE = "bm_refresh";

export const API_URL = (process.env.API_URL ?? "http://localhost:8000").replace(/\/$/, "");

const secure = process.env.NODE_ENV === "production";

export type TokenPair = {
  access_token: string;
  refresh_token: string;
  expires_in: number;
};

export function setSessionCookies(response: NextResponse, tokens: TokenPair): void {
  const base = { httpOnly: true, secure, sameSite: "strict" as const, path: "/" };
  response.cookies.set(ACCESS_COOKIE, tokens.access_token, {
    ...base,
    maxAge: Math.max(60, tokens.expires_in - 30),
  });
  response.cookies.set(REFRESH_COOKIE, tokens.refresh_token, {
    ...base,
    maxAge: 7 * 24 * 60 * 60,
  });
}

export function clearSessionCookies(response: NextResponse): void {
  response.cookies.delete(ACCESS_COOKIE);
  response.cookies.delete(REFRESH_COOKIE);
}

export async function refreshTokens(refreshToken: string): Promise<TokenPair | null> {
  const response = await fetch(`${API_URL}/auth/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: refreshToken }),
    cache: "no-store",
  });
  if (!response.ok) return null;
  return (await response.json()) as TokenPair;
}
