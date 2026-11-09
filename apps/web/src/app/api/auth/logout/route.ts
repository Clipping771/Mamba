import { NextResponse, type NextRequest } from "next/server";

import { clearSessionCookies } from "@/lib/server/session";

export async function POST(request: NextRequest) {
  if (request.headers.get("x-bm-csrf") !== "1") {
    return NextResponse.json({ detail: { code: "csrf", message: "bad request" } }, { status: 403 });
  }
  const response = NextResponse.json({ ok: true });
  clearSessionCookies(response);
  return response;
}
