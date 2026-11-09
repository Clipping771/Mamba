"use client";

import createClient, { type Middleware } from "openapi-fetch";

import type { components, paths } from "@/lib/api/schema";

export type Schemas = components["schemas"];
export type CaseSummary = Schemas["CaseSummary"];
export type Evidence = Schemas["EvidenceOut"];
export type Finding = Schemas["FindingOut"];
export type ReviewItem = Schemas["ReviewQueueItem"];
export type Note = Schemas["NoteOut"];
export type ArchiveJob = Schemas["ArchiveJobOut"];
export type Activity = Schemas["ActivityOut"];
export type Me = Schemas["MeOut"];
export type User = Schemas["UserOut"];
export type Role = Schemas["Role"];
export type CaseStatus = Schemas["CaseStatus"];
export type CaseCategory = Schemas["CaseCategory"];
export type FindingStatus = Schemas["FindingStatus"];
export type Org = Schemas["OrgOut"];
export type AuditEntry = Schemas["AuditEntryOut"];
export type Invite = Schemas["InviteOut"];

export const CSRF_HEADERS = { "x-bm-csrf": "1" } as const;

/** Error carrying the API's machine-readable code. */
export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
  ) {
    super(message);
  }
}

export function toApiError(status: number, body: unknown): ApiError {
  const detail = (body as { detail?: unknown } | undefined)?.detail;
  if (detail && typeof detail === "object" && !Array.isArray(detail)) {
    const d = detail as { code?: string; message?: string };
    return new ApiError(status, d.code ?? "error", d.message ?? d.code ?? "Request failed");
  }
  if (Array.isArray(detail)) {
    // FastAPI validation errors.
    const first = detail[0] as { loc?: unknown[]; msg?: string } | undefined;
    const field = first?.loc?.slice(1).join(".") ?? "";
    return new ApiError(status, "validation", `${field ? `${field}: ` : ""}${first?.msg ?? "invalid input"}`);
  }
  if (status === 429) return new ApiError(status, "rate_limited", "Too many attempts. Try again later.");
  return new ApiError(status, "error", `Request failed (${status})`);
}

const csrf: Middleware = {
  onRequest({ request }) {
    request.headers.set("x-bm-csrf", "1");
    return request;
  },
  onResponse({ response }) {
    if (response.status === 401 && typeof window !== "undefined") {
      const here = window.location.pathname;
      const isPublic = ["/login", "/invite", "/reset-password", "/forgot-password", "/apply"].some((p) =>
        here.startsWith(p),
      );
      // Outside React (fetch middleware): a full navigation also drops stale client state.
      // eslint-disable-next-line @next/next/no-location-assign-relative-destination
      if (!isPublic) window.location.href = `/login?next=${encodeURIComponent(here)}`;
    }
    return response;
  },
};

export const api = createClient<paths>({ baseUrl: "/api/bm" });
api.use(csrf);

/** Unwrap an openapi-fetch result: return data or throw ApiError. */
export async function call<T>(
  promise: Promise<{ data?: T; error?: unknown; response: Response }>,
): Promise<T> {
  const { data, error, response } = await promise;
  if (!response.ok || data === undefined) {
    throw toApiError(response.status, error);
  }
  return data;
}

export const STATUS_LABELS: Record<CaseStatus, string> = {
  open: "Open",
  investigating: "Investigating",
  review: "In review",
  closed: "Closed",
};

export const CATEGORY_LABELS: Record<CaseCategory, string> = {
  job_scam: "Job scam",
  investment_scam: "Investment scam",
  phishing: "Phishing",
  marketplace: "Marketplace",
  romance_scam: "Romance scam",
  impersonation: "Impersonation",
  other: "Other",
};

export const ROLE_LABELS: Record<Role, string> = {
  investigator: "Investigator",
  reviewer: "Reviewer",
  admin: "Org admin",
  platform_admin: "Platform admin",
};

export function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  const d = new Date(value);
  return `${d.toISOString().slice(0, 16).replace("T", " ")} UTC`;
}

/** E1, E2… in capture order, excluding reports: the same numbering the PDF report uses. */
export function evidenceRefs(items: Evidence[]): Map<string, string> {
  const ordered = items
    .filter((e) => e.type !== "report")
    .sort((a, b) => a.captured_at.localeCompare(b.captured_at));
  return new Map(ordered.map((e, i) => [e.id, `E${i + 1}`] as const));
}

export function formatBytes(size: number | null | undefined): string {
  if (size == null) return "—";
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / 1024 / 1024).toFixed(1)} MB`;
}
