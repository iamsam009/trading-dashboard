import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

/**
 * Route protection middleware.
 *
 * Reads the `access_token` cookie (HttpOnly, set by the client after login)
 * and redirects unauthenticated users to /login.
 *
 * Protected routes: /dashboard, /strategies, /backtest
 * Public routes:    /login, /signup, / (root), /api/*, /_next/*, /favicon.ico
 */

const PROTECTED_PREFIXES = ["/dashboard", "/strategies", "/backtest"];
const PUBLIC_PREFIXES = ["/login", "/signup", "/api", "/_next", "/favicon.ico"];

function isProtected(pathname: string): boolean {
    return PROTECTED_PREFIXES.some((p) => pathname === p || pathname.startsWith(p + "/"));
}

function isPublic(pathname: string): boolean {
    if (pathname === "/") return true;
    return PUBLIC_PREFIXES.some((p) => pathname.startsWith(p));
}

export function middleware(request: NextRequest) {
    const { pathname } = request.nextUrl;

    // Skip middleware for public / static paths
    if (isPublic(pathname)) {
        return NextResponse.next();
    }

    // If not a protected route, allow through
    if (!isProtected(pathname)) {
        return NextResponse.next();
    }

    // Check for the access token cookie (set by AuthProvider on login/signup).
    // The cookie approach works because cookies are automatically included
    // in browser page navigations, unlike the Authorization header.
    const token = request.cookies.get("auth_token")?.value;
    const hasToken = !!token;

    if (!hasToken) {
        const loginUrl = new URL("/login", request.url);
        loginUrl.searchParams.set("redirect", pathname);
        return NextResponse.redirect(loginUrl);
    }

    return NextResponse.next();
}

export const config = {
    matcher: [
        /*
         * Match all request paths except:
         * - _next/static (static files)
         * - _next/image (image optimization)
         * - favicon.ico
         */
        "/((?!_next/static|_next/image|favicon.ico).*)",
    ],
};