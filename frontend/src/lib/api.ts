/**
 * Shared Axios instance with JWT authentication interceptors.
 *
 * All dashboard components should import this instance instead of creating
 * their own.  It automatically:
 *  - Attaches the Bearer token from localStorage
 *  - Handles 401 responses by redirecting to /login
 *  - Shows react-hot-toast errors for failed requests
 *  - Uses the Next.js API proxy (/api/:path*) so no CORS issues in dev
 */

import axios, { AxiosError, InternalAxiosRequestConfig } from "axios";
import toast from "react-hot-toast";

// ── Public / exported types ──────────────────────────────────

export interface ApiErrorDetail {
    message?: string;
    detail?: string | { message?: string };
    errors?: string[];
}

// ── Axios instance ───────────────────────────────────────────

const api = axios.create({
    baseURL: "/api/v1",
    headers: { "Content-Type": "application/json" },
    timeout: 30_000,
});

// ── Request interceptor – attach JWT ────────────────────────

api.interceptors.request.use((config: InternalAxiosRequestConfig) => {
    if (typeof window !== "undefined") {
        const token = localStorage.getItem("access_token");
        if (token && config.headers) {
            config.headers.Authorization = `Bearer ${token}`;
        }
    }
    return config;
});

// ── Response interceptor – handle errors ────────────────────

api.interceptors.response.use(
    (response) => response,
    (error: AxiosError<ApiErrorDetail>) => {
        // 401 → redirect to login (unless already on login page)
        if (error.response?.status === 401) {
            if (
                typeof window !== "undefined" &&
                !window.location.pathname.startsWith("/login")
            ) {
                localStorage.removeItem("access_token");
                localStorage.removeItem("refresh_token");
                window.location.href = "/login";
            }
            return Promise.reject(error);
        }

        // Extract a human-readable message
        const detail = error.response?.data?.detail;
        const msg: string =
            typeof detail === "object" && detail !== null
                ? (detail as Record<string, unknown>).message as string ||
                JSON.stringify(detail)
                : (detail as string) ||
                error.response?.data?.message ||
                error.message ||
                "Request failed";

        toast.error(msg);
        return Promise.reject(error);
    },
);

export default api;