import { NextResponse, type NextRequest } from "next/server";

import { API_URL, setSessionCookies, type TokenPair } from "@/lib/server/session";

export async function POST(request: NextRequest) {
  if (request.headers.get("x-bm-csrf") !== "1") {
    return NextResponse.json({ detail: { code: "csrf", message: "bad request" } }, { status: 403 });
  }
  const body = await request.text();
  const upstream = await fetch(`${API_URL}/auth/login`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      // Lets the API rate-limit per real client.
      "X-Forwarded-For": request.headers.get("x-forwarded-for") ?? "",
    },
    body,
    cache: "no-store",
  });
  const data: unknown = await upstream.json().catch(() => ({}));
  if (!upstream.ok) {
    return NextResponse.json(data, { status: upstream.status });
  }
  const response = NextResponse.json({ ok: true });
  setSessionCookies(response, data as TokenPair);
  return response;
}
