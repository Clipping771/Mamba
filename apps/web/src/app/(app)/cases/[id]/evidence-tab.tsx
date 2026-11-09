"use client";

import { useState } from "react";

import { Badge, Button, EmptyState, ErrorBanner, Loading, Mono } from "@/components/ui";
import { api, call, evidenceRefs, formatBytes, formatDate, type Evidence } from "@/lib/api";
import { useQuery } from "@/lib/hooks";

const TYPE_TONES = { url: "blue", file: "neutral", screenshot: "violet", note: "amber", report: "green" } as const;

export function EvidenceTab({
  caseId,
  canEdit,
  names,
  onChange,
}: {
  caseId: string;
  canEdit: boolean;
  names: Map<string, string>;
  onChange: () => void;
}) {
  const evidence = useQuery(["evidence", caseId], () =>
    call(api.GET("/cases/{case_id}/evidence", { params: { path: { case_id: caseId } } })),
  );
  if (evidence.isLoading) return <Loading />;
  if (evidence.error) return <ErrorBanner error={evidence.error} />;
  const items = evidence.data ?? [];
  if (items.length === 0) {
    return <EmptyState title="No evidence yet">Upload a file, record a URL or note, or archive a web page.</EmptyState>;
  }
  const refs = evidenceRefs(items);
  return (
    <ol className="relative space-y-4 border-l border-zinc-800 pl-6">
      {items.map((item) => (
        <EvidenceItem
          key={item.id}
          item={item}
          refNo={refs.get(item.id) ?? "report"}
          canEdit={canEdit}
          names={names}
          onChange={() => {
            evidence.mutate();
            onChange();
          }}
        />
      ))}
    </ol>
  );
}

function EvidenceItem({
  item,
  refNo,
  canEdit,
  names,
  onChange,
}: {
  item: Evidence;
  refNo: string;
  canEdit: boolean;
  names: Map<string, string>;
  onChange: () => void;
}) {
  const [verify, setVerify] = useState<{ match: boolean; actual: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  async function runVerify() {
    setBusy(true);
    setError(null);
    try {
      const result = await call(api.GET("/evidence/{evidence_id}/verify", { params: { path: { evidence_id: item.id } } }));
      setVerify({ match: result.match, actual: result.actual });
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  async function exclude() {
    const reason = window.prompt("Why should this item be excluded? (kept, but not relied upon)");
    if (!reason) return;
    setBusy(true);
    setError(null);
    try {
      await call(
        api.POST("/evidence/{evidence_id}/exclude", { params: { path: { evidence_id: item.id } }, body: { reason } }),
      );
      onChange();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <li className="relative">
      <span className="absolute top-2 -left-[29px] h-2.5 w-2.5 rounded-full border-2 border-zinc-950 bg-emerald-400" />
      <div className={`rounded-lg border p-4 ${item.excluded ? "border-zinc-800 bg-zinc-950 opacity-70" : "border-zinc-800 bg-zinc-900/60"}`}>
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-mono text-xs text-zinc-500">{refNo}</span>
          <Badge tone={TYPE_TONES[item.type]}>{item.type}</Badge>
          <span className="font-medium text-zinc-100">{item.title || "(untitled)"}</span>
          {item.excluded && <Badge tone="red">excluded</Badge>}
        </div>
        <div className="mt-1 text-xs text-zinc-500">
          Captured {formatDate(item.captured_at)} by {names.get(item.captured_by) ?? "a former member"}
          {item.size != null && ` · ${item.mime} · ${formatBytes(item.size)}`}
          {item.http_status != null && ` · HTTP ${item.http_status}`}
        </div>
        {item.description && <p className="mt-2 text-sm whitespace-pre-wrap text-zinc-300">{item.description}</p>}
        {item.source_url && (
          <div className="mt-2 text-xs">
            <span className="text-zinc-500">Source: </span>
            <Mono>{item.source_url}</Mono>
            {item.final_url && item.final_url !== item.source_url && (
              <>
                <span className="text-zinc-500"> → </span>
                <Mono>{item.final_url}</Mono>
              </>
            )}
          </div>
        )}
        {item.sha256 && (
          <div className="mt-2 text-xs">
            <span className="text-zinc-500">SHA-256: </span>
            <Mono>{item.sha256}</Mono>
          </div>
        )}
        {item.excluded && <p className="mt-2 text-xs text-red-300">Excluded: {item.excluded_reason}</p>}
        {verify && (
          <p className={`mt-2 text-sm ${verify.match ? "text-emerald-300" : "font-semibold text-red-300"}`}>
            {verify.match ? "✓ Integrity verified: stored content matches the capture hash." : `✗ HASH MISMATCH (now ${verify.actual})`}
          </p>
        )}
        <ErrorBanner error={error} />
        {item.sha256 && (
          <div className="mt-3 flex flex-wrap gap-2">
            <Button variant="secondary" busy={busy} onClick={runVerify}>
              Verify integrity
            </Button>
            <a
              href={`/api/bm/evidence/${item.id}/content`}
              className="inline-flex items-center rounded-md border border-zinc-700 px-3.5 py-2 text-sm text-zinc-100 hover:bg-zinc-800"
            >
              Download
            </a>
            {canEdit && !item.excluded && (
              <Button variant="ghost" busy={busy} onClick={exclude}>
                Exclude…
              </Button>
            )}
          </div>
        )}
        {!item.sha256 && canEdit && !item.excluded && (
          <div className="mt-3">
            <Button variant="ghost" busy={busy} onClick={exclude}>
              Exclude…
            </Button>
          </div>
        )}
      </div>
    </li>
  );
}
