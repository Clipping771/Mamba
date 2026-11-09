"use client";

import { useState } from "react";

import { Badge, Button, Card, ErrorBanner, LinkButton, Loading, Mono, Notice, PageHeader } from "@/components/ui";
import { api, call, formatDate } from "@/lib/api";
import { useMe, useQuery } from "@/lib/hooks";

export function ReportView({ caseId }: { caseId: string }) {
  const { data: me } = useMe();
  const preview = useQuery(["report-preview", caseId], () =>
    call(api.GET("/cases/{case_id}/report/preview", { params: { path: { case_id: caseId } } })),
  );
  const evidence = useQuery(["evidence", caseId], () =>
    call(api.GET("/cases/{case_id}/evidence", { params: { path: { case_id: caseId } } })),
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const reports = (evidence.data ?? []).filter((e) => e.type === "report");

  async function generate() {
    setBusy(true);
    setError(null);
    try {
      await call(api.POST("/cases/{case_id}/reports", { params: { path: { case_id: caseId } } }));
      await evidence.mutate();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader
        title="Case report"
        subtitle="Only verified findings appear. Draft, rejected and AI-drafted material is never included."
        actions={<LinkButton href={`/cases/${caseId}`}>← Back to case</LinkButton>}
      />
      <ErrorBanner error={error ?? preview.error} />
      {preview.data && (
        <div className="mb-4 flex flex-wrap items-center gap-3">
          <Badge tone="green">{preview.data.verified_findings} verified findings</Badge>
          <Badge>{preview.data.evidence_items} evidence items</Badge>
          {preview.data.chain_ok ? <Badge tone="green">Audit chain intact</Badge> : <Badge tone="red">Audit chain BROKEN</Badge>}
          {me?.role === "reviewer" &&
            (preview.data.pdf_available ? (
              <Button busy={busy} onClick={generate} disabled={!preview.data.chain_ok}>
                Generate PDF
              </Button>
            ) : (
              <Notice tone="amber">The PDF engine is not installed on this server.</Notice>
            ))}
          {me?.role !== "reviewer" && <span className="text-sm text-zinc-500">A reviewer generates the PDF.</span>}
        </div>
      )}
      {reports.length > 0 && (
        <Card className="mb-6">
          <h2 className="mb-3 font-medium text-white">Generated reports</h2>
          <ul className="space-y-2 text-sm">
            {reports.map((r) => (
              <li key={r.id} className="flex flex-wrap items-center justify-between gap-2">
                <span>
                  {r.title} <span className="text-zinc-500">· {formatDate(r.captured_at)}</span>
                  <br />
                  <Mono>sha256 {r.sha256}</Mono>
                </span>
                <a
                  href={`/api/bm/evidence/${r.id}/content`}
                  className="rounded-md border border-zinc-700 px-3 py-1.5 text-zinc-100 hover:bg-zinc-800"
                >
                  Download PDF
                </a>
              </li>
            ))}
          </ul>
        </Card>
      )}
      {preview.isLoading && <Loading label="Building preview…" />}
      {preview.data && (
        <div className="overflow-hidden rounded-lg border border-zinc-800 bg-white">
          {/* Sandboxed: the preview HTML is server-rendered and escaped, and gets no script or same-origin access. */}
          <iframe title="Report preview" sandbox="" srcDoc={preview.data.html} className="h-[80vh] w-full" />
        </div>
      )}
    </>
  );
}
