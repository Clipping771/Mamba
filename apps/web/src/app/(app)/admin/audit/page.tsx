"use client";

import { useState } from "react";

import { Badge, Button, Card, ErrorBanner, Input, Loading, Mono, PageHeader } from "@/components/ui";
import { api, call, formatDate } from "@/lib/api";
import { useQuery } from "@/lib/hooks";

export default function AuditPage() {
  const [offset, setOffset] = useState(0);
  const [action, setAction] = useState("");
  const limit = 100;
  const log = useQuery(["audit", offset, action], () =>
    call(api.GET("/admin/audit", { params: { query: { limit, offset, action: action || undefined } } })),
  );
  const [check, setCheck] = useState<{ ok: boolean; entries_checked: number; first_bad_id?: number | null; reason?: string | null } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  async function verify() {
    setBusy(true);
    setError(null);
    try {
      setCheck(await call(api.GET("/admin/audit/verify")));
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader
        title="Audit log"
        subtitle="Append-only and hash-chained: each entry includes the hash of the one before it."
        actions={
          <Button busy={busy} onClick={verify}>
            Verify chain
          </Button>
        }
      />
      <ErrorBanner error={error ?? log.error} />
      {check && (
        <Card className="mb-4">
          {check.ok ? (
            <p className="text-emerald-300">✓ Chain intact. {check.entries_checked} entries verified.</p>
          ) : (
            <p className="font-semibold text-red-300">
              ✗ Chain broken at entry #{check.first_bad_id}: {check.reason}. Stop and investigate: records may have
              been altered.
            </p>
          )}
        </Card>
      )}
      <div className="mb-3 max-w-sm">
        <Input
          placeholder="Filter by action, e.g. evidence.capture"
          value={action}
          onChange={(e) => {
            setAction(e.target.value.trim());
            setOffset(0);
          }}
        />
      </div>
      {log.isLoading && <Loading />}
      {log.data && (
        <>
          <div className="overflow-x-auto rounded-lg border border-zinc-800">
            <table className="w-full text-left text-sm">
              <thead className="bg-zinc-900 text-xs text-zinc-400 uppercase">
                <tr>
                  <th className="px-3 py-2 font-medium">#</th>
                  <th className="px-3 py-2 font-medium">Time</th>
                  <th className="px-3 py-2 font-medium">Action</th>
                  <th className="px-3 py-2 font-medium">Target</th>
                  <th className="px-3 py-2 font-medium">Payload</th>
                  <th className="px-3 py-2 font-medium">Hash</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-800">
                {log.data.items.map((e) => (
                  <tr key={e.id}>
                    <td className="px-3 py-2 text-xs text-zinc-500">{e.id}</td>
                    <td className="px-3 py-2 text-xs whitespace-nowrap text-zinc-400">{formatDate(e.ts)}</td>
                    <td className="px-3 py-2">
                      <Badge tone={e.action.includes("fail") ? "red" : "neutral"}>{e.action}</Badge>
                    </td>
                    <td className="px-3 py-2 text-xs text-zinc-400">
                      {e.target_type} <Mono>{e.target_id?.slice(0, 8)}</Mono>
                    </td>
                    <td className="max-w-md px-3 py-2">
                      <Mono className="line-clamp-2">{JSON.stringify(e.payload)}</Mono>
                    </td>
                    <td className="px-3 py-2">
                      <Mono>{e.hash.slice(0, 12)}</Mono>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="mt-3 flex items-center justify-between text-sm text-zinc-400">
            <span>{log.data.total} entries</span>
            <div className="flex gap-3">
              <button disabled={offset === 0} onClick={() => setOffset(offset - limit)} className="disabled:opacity-40">
                ← Newer
              </button>
              <button
                disabled={offset + limit >= log.data.total}
                onClick={() => setOffset(offset + limit)}
                className="disabled:opacity-40"
              >
                Older →
              </button>
            </div>
          </div>
        </>
      )}
    </>
  );
}
