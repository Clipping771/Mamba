/**
 * Backend-for-frontend proxy: /api/bm/<path> -> API_URL/<path>.
 * Attaches the access token from the httpOnly cookie, refreshes it when it expires, and
 * requires a custom CSRF header on every state-changing request.
 */
import { NextResponse, type NextRequest } from "next/server";

import {
  ACCESS_COOKIE,
  API_URL,
  clearSessionCookies,
  REFRESH_COOKIE,
  refreshTokens,
  setSessionCookies,
  type TokenPair,
} from "@/lib/server/session";

const PASS_RESPONSE_HEADERS = [
  "content-type",
  "content-disposition",
  "content-security-policy",
  "x-content-sha256",
  "retry-after",
];

async function forward(
  request: NextRequest,
  path: string[],
  body: ArrayBuffer | undefined,
  accessToken: string | undefined,
): Promise<Response> {
  const target = new URL(`${API_URL}/${path.map(encodeURIComponent).join("/")}`);
  target.search = request.nextUrl.search;
  const headers = new Headers();
  const contentType = request.headers.get("content-type");
  if (contentType) headers.set("content-type", contentType);
  headers.set("accept", request.headers.get("accept") ?? "application/json");
  const forwardedFor = request.headers.get("x-forwarded-for");
  if (forwardedFor) headers.set("x-forwarded-for", forwardedFor);
  if (accessToken) headers.set("authorization", `Bearer ${accessToken}`);
  return fetch(target, {
    method: request.method,
    headers,
    body: body && body.byteLength > 0 ? body : undefined,
    cache: "no-store",
    redirect: "manual",
  });
}

async function handle(request: NextRequest, ctx: RouteContext<"/api/bm/[...path]">) {
  const { path } = await ctx.params;
  if (request.method !== "GET" && request.headers.get("x-bm-csrf") !== "1") {
    return NextResponse.json({ detail: { code: "csrf", message: "bad request" } }, { status: 403 });
  }
  const body = request.method === "GET" ? undefined : await request.arrayBuffer();
  let access = request.cookies.get(ACCESS_COOKIE)?.value;
  const refresh = request.cookies.get(REFRESH_COOKIE)?.value;
  let renewed: TokenPair | null = null;

  if (!access && refresh) {
    renewed = await refreshTokens(refresh);
    access = renewed?.access_token;
  }
  let upstream = await forward(request, path, body, access);
  if (upstream.status === 401 && refresh && !renewed) {
    renewed = await refreshTokens(refresh);
    if (renewed) upstream = await forward(request, path, body, renewed.access_token);
  }

  const headers = new Headers();
  for (const name of PASS_RESPONSE_HEADERS) {
    const value = upstream.headers.get(name);
    if (value) headers.set(name, value);
  }
  headers.set("cache-control", "no-store");
  const response = new NextResponse(upstream.body, { status: upstream.status, headers });
  if (renewed) setSessionCookies(response, renewed);
  if (upstream.status === 401 && refresh && !renewed) clearSessionCookies(response);
  return response;
}

export const GET = handle;
export const POST = handle;
export const PATCH = handle;
