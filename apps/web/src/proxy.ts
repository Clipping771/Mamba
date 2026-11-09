import { NextResponse, type NextRequest } from "next/server";

const PUBLIC_PATHS = ["/login", "/apply", "/invite", "/forgot-password", "/reset-password"];

/** Send signed-out visitors to /login. Real authorisation happens in the API. */
export function proxy(request: NextRequest) {
  const { pathname, search } = request.nextUrl;
  const isPublic = PUBLIC_PATHS.some((p) => pathname === p || pathname.startsWith(`${p}/`));
  const signedIn = request.cookies.has("bm_refresh");
  if (!isPublic && !signedIn) {
    const url = new URL("/login", request.url);
    if (pathname !== "/") url.searchParams.set("next", `${pathname}${search}`);
    return NextResponse.redirect(url);
  }
  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!api|_next/static|_next/image|favicon.ico|.*\\.(?:png|svg|ico|txt)$).*)"],
};
