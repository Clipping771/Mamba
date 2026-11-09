"use client";

import { useState } from "react";

import { Button, Card, EmptyState, ErrorBanner, Loading, Mono, Notice, PageHeader, Select, StatusBadge } from "@/components/ui";
import { api, call, formatDate, type Org, type Schemas } from "@/lib/api";
import { useQuery } from "@/lib/hooks";

type OrgStatus = Schemas["OrgStatus"];

export default function PlatformOrgsPage() {
  const [status, setStatus] = useState<OrgStatus | "">("pending");
  const orgs = useQuery(["orgs", status], () =>
    call(api.GET("/platform/orgs", { params: { query: { status: status || undefined } } })),
  );
  const [invite, setInvite] = useState<{ url: string; emailed: boolean } | null>(null);
  const [error, setError] = useState<unknown>(null);

  return (
    <>
      <PageHeader
        title="Organisations"
        subtitle="Vet every applicant. Approving one creates an admin invitation for its contact."
        actions={
          <Select value={status} onChange={(e) => setStatus(e.target.value as OrgStatus | "")} aria-label="Filter">
            <option value="pending">Pending</option>
            <option value="active">Active</option>
            <option value="suspended">Suspended</option>
            <option value="rejected">Rejected</option>
            <option value="">All</option>
          </Select>
        }
      />
      {invite && (
        <Notice>
          Admin invitation {invite.emailed ? "emailed and" : "created (email not configured):"} <Mono className="text-emerald-100">{invite.url}</Mono>
        </Notice>
      )}
      <ErrorBanner error={error ?? orgs.error} />
      {orgs.isLoading && <Loading />}
      {orgs.data?.length === 0 && <EmptyState title="No organisations here" />}
      <div className="mt-4 space-y-3">
        {orgs.data?.map((org) => (
          <OrgCard
            key={org.id}
            org={org}
            onInvite={setInvite}
            onError={setError}
            onChange={() => orgs.mutate()}
          />
        ))}
      </div>
    </>
  );
}

function OrgCard({
  org,
  onInvite,
  onError,
  onChange,
}: {
  org: Org;
  onInvite: (v: { url: string; emailed: boolean }) => void;
  onError: (e: unknown) => void;
  onChange: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const path = { params: { path: { org_id: org.id } } };

  async function run(action: () => Promise<void>) {
    setBusy(true);
    onError(null);
    try {
      await action();
      onChange();
    } catch (err) {
      onError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="font-medium text-white">{org.name}</span>
          <StatusBadge status={org.status} />
        </div>
        <span className="text-xs text-zinc-500">applied {formatDate(org.created_at)}</span>
      </div>
      <p className="mt-2 text-sm text-zinc-400">
        {org.contact_name} · {org.contact_email}
      </p>
      <p className="mt-2 text-sm whitespace-pre-wrap text-zinc-200">{org.purpose}</p>
      <div className="mt-3 flex flex-wrap gap-2">
        {org.status === "pending" && (
          <>
            <Button
              busy={busy}
              onClick={() =>
                run(async () => {
                  const result = await call(api.POST("/platform/orgs/{org_id}/approve", path));
                  onInvite({ url: result.admin_invite_url, emailed: result.emailed });
                })
              }
            >
              Approve
            </Button>
            <Button
              variant="danger"
              busy={busy}
              onClick={() => {
                const reason = window.prompt("Reason (kept in the audit log)") ?? undefined;
                run(async () => {
                  await call(api.POST("/platform/orgs/{org_id}/reject", { ...path, body: { reason } }));
                });
              }}
            >
              Reject
            </Button>
          </>
        )}
        {org.status === "active" && (
          <Button
            variant="danger"
            busy={busy}
            onClick={() => {
              const reason = window.prompt("Why suspend this organisation? Its members are signed out immediately.");
              if (reason)
                run(async () => {
                  await call(api.POST("/platform/orgs/{org_id}/suspend", { ...path, body: { reason } }));
                });
            }}
          >
            Suspend
          </Button>
        )}
        {org.status === "suspended" && (
          <Button
            variant="secondary"
            busy={busy}
            onClick={() =>
              run(async () => {
                await call(api.POST("/platform/orgs/{org_id}/reactivate", path));
              })
            }
          >
            Reactivate
          </Button>
        )}
      </div>
    </Card>
  );
}
