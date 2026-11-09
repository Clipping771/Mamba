"use client";

import { EmptyState, ErrorBanner, Loading, Mono } from "@/components/ui";
import { api, call, formatDate } from "@/lib/api";
import { useQuery } from "@/lib/hooks";

const ACTION_LABELS: Record<string, string> = {
  "case.create": "Case created",
  "case.update": "Case edited",
  "case.transition": "Status changed",
  "evidence.capture": "Evidence captured",
  "evidence.verify": "Integrity verified",
  "evidence.integrity_failure": "INTEGRITY FAILURE",
  "evidence.access": "Evidence downloaded",
  "evidence.exclude": "Evidence excluded",
  "note.create": "Note added",
  "archive.request": "Archive requested",
  "archive.done": "Archive completed",
  "archive.failed": "Archive failed",
  "finding.create": "Finding drafted",
  "finding.update": "Finding revised",
  "finding.submit": "Finding submitted",
  "finding.verify": "Finding verified",
  "finding.reject": "Finding rejected",
  "archivist.run": "ARCHIVIST draft generated",
  "report.generate": "Report generated",
};

function describe(payload: Record<string, unknown>): string {
  if (payload.from && payload.to) return `${String(payload.from)} → ${String(payload.to)}`;
  if (typeof payload.sha256 === "string") return `sha256 ${payload.sha256.slice(0, 16)}…`;
  if (typeof payload.reason === "string") return payload.reason;
  if (typeof payload.url === "string") return payload.url;
  return "";
}

export function ActivityTab({ caseId }: { caseId: string }) {
  const activity = useQuery(["activity", caseId], () =>
    call(api.GET("/cases/{case_id}/activity", { params: { path: { case_id: caseId } } })),
  );
  if (activity.isLoading) return <Loading />;
  if (activity.error) return <ErrorBanner error={activity.error} />;
  if (!activity.data?.length) return <EmptyState title="No activity yet" />;
  return (
    <>
      <p className="mb-3 text-sm text-zinc-400">
        Every action is recorded in an append-only, hash-chained audit log. Each row shows the first characters of
        its chain hash.
      </p>
      <div className="overflow-x-auto rounded-lg border border-zinc-800">
        <table className="w-full text-left text-sm">
          <thead className="bg-zinc-900 text-xs text-zinc-400 uppercase">
            <tr>
              <th className="px-4 py-2 font-medium">Time</th>
              <th className="px-4 py-2 font-medium">Action</th>
              <th className="px-4 py-2 font-medium">By</th>
              <th className="px-4 py-2 font-medium">Detail</th>
              <th className="px-4 py-2 font-medium">Hash</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-zinc-800">
            {activity.data.map((a) => (
              <tr key={a.id}>
                <td className="px-4 py-2 text-xs whitespace-nowrap text-zinc-400">{formatDate(a.ts)}</td>
                <td className={`px-4 py-2 ${a.action === "evidence.integrity_failure" ? "font-semibold text-red-300" : "text-zinc-200"}`}>
                  {ACTION_LABELS[a.action] ?? a.action}
                </td>
                <td className="px-4 py-2 text-zinc-300">{a.actor_name ?? "system"}</td>
                <td className="max-w-xs truncate px-4 py-2 text-xs text-zinc-400">{describe(a.payload)}</td>
                <td className="px-4 py-2">
                  <Mono>{a.hash.slice(0, 12)}</Mono>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
