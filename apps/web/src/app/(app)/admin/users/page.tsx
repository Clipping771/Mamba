"use client";

import { useState, type FormEvent } from "react";

import {
  Badge,
  Button,
  Card,
  ErrorBanner,
  Field,
  Input,
  Loading,
  Mono,
  Notice,
  PageHeader,
  Select,
} from "@/components/ui";
import { api, call, formatDate, ROLE_LABELS, type Role, type User } from "@/lib/api";
import { useMe, useQuery } from "@/lib/hooks";

const ASSIGNABLE: Role[] = ["investigator", "reviewer", "admin"];

export default function AdminUsersPage() {
  const { data: me } = useMe();
  const users = useQuery(["admin-users"], () => call(api.GET("/admin/users")));
  const invites = useQuery(["admin-invites"], () => call(api.GET("/admin/invitations")));
  const [link, setLink] = useState<{ label: string; url: string; emailed: boolean } | null>(null);
  const [error, setError] = useState<unknown>(null);

  return (
    <>
      <PageHeader title="Users & invitations" subtitle={me?.org_name ?? undefined} />
      <div className="space-y-6">
        {link && (
          <Notice>
            <div className="space-y-1">
              <div>
                {link.label} {link.emailed ? "(also emailed)" : "(email is not configured: share it securely)"}
              </div>
              <Mono className="text-emerald-100">{link.url}</Mono>
              <div>
                <button className="underline" onClick={() => navigator.clipboard.writeText(link.url)}>
                  Copy link
                </button>
              </div>
            </div>
          </Notice>
        )}
        <ErrorBanner error={error ?? users.error ?? invites.error} />
        <InviteForm
          onCreated={(url, emailed) => {
            setLink({ label: "Invitation link (valid 7 days, single use):", url, emailed });
            invites.mutate();
          }}
        />
        <Card>
          <h2 className="mb-3 font-medium text-white">Members</h2>
          {users.isLoading && <Loading />}
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="text-xs text-zinc-400 uppercase">
                <tr>
                  <th className="py-2 pr-4 font-medium">Name</th>
                  <th className="py-2 pr-4 font-medium">Role</th>
                  <th className="py-2 pr-4 font-medium">2FA</th>
                  <th className="py-2 pr-4 font-medium">Last sign-in</th>
                  <th className="py-2 font-medium">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-800">
                {users.data?.map((u) => (
                  <UserRow
                    key={u.id}
                    user={u}
                    isSelf={u.id === me?.id}
                    onChanged={() => users.mutate()}
                    onLink={(url, emailed) => setLink({ label: `Password reset link for ${u.name}:`, url, emailed })}
                    onError={setError}
                  />
                ))}
              </tbody>
            </table>
          </div>
        </Card>
        <Card>
          <h2 className="mb-3 font-medium text-white">Pending invitations</h2>
          {invites.data?.length === 0 && <p className="text-sm text-zinc-500">None.</p>}
          <ul className="divide-y divide-zinc-800 text-sm">
            {invites.data?.map((inv) => (
              <li key={inv.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
                <span>
                  {inv.email} <Badge>{inv.role ? ROLE_LABELS[inv.role] : "?"}</Badge>
                  <span className="ml-2 text-xs text-zinc-500">expires {formatDate(inv.expires_at)}</span>
                </span>
                <Button
                  variant="ghost"
                  onClick={async () => {
                    try {
                      await call(api.POST("/admin/invitations/{invite_id}/revoke", { params: { path: { invite_id: inv.id } } }));
                      invites.mutate();
                    } catch (err) {
                      setError(err);
                    }
                  }}
                >
                  Revoke
                </Button>
              </li>
            ))}
          </ul>
        </Card>
      </div>
    </>
  );
}

function InviteForm({ onCreated }: { onCreated: (url: string, emailed: boolean) => void }) {
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<Role>("investigator");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const result = await call(api.POST("/admin/invitations", { body: { email, role } }));
      setEmail("");
      onCreated(result.invite_url, result.emailed);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <form onSubmit={submit} className="grid items-end gap-3 sm:grid-cols-[1fr_200px_auto]">
        <Field label="Invite by email">
          <Input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
        </Field>
        <Field label="Role">
          <Select value={role} onChange={(e) => setRole(e.target.value as Role)}>
            {ASSIGNABLE.map((r) => (
              <option key={r} value={r}>
                {ROLE_LABELS[r]}
              </option>
            ))}
          </Select>
        </Field>
        <Button type="submit" busy={busy}>
          Send invite
        </Button>
      </form>
      <div className="mt-3">
        <ErrorBanner error={error} />
      </div>
    </Card>
  );
}

function UserRow({
  user,
  isSelf,
  onChanged,
  onLink,
  onError,
}: {
  user: User;
  isSelf: boolean;
  onChanged: () => void;
  onLink: (url: string, emailed: boolean) => void;
  onError: (err: unknown) => void;
}) {
  const [busy, setBusy] = useState(false);
  const path = { params: { path: { user_id: user.id } } };

  async function run(action: () => Promise<void>) {
    setBusy(true);
    try {
      await action();
      onChanged();
    } catch (err) {
      onError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <tr className={user.is_active ? "" : "opacity-50"}>
      <td className="py-2 pr-4">
        <div className="text-zinc-100">
          {user.name} {isSelf && <span className="text-xs text-zinc-500">(you)</span>}
        </div>
        <div className="text-xs text-zinc-500">{user.email}</div>
      </td>
      <td className="py-2 pr-4">
        <Select
          aria-label={`Role of ${user.name}`}
          value={user.role}
          disabled={isSelf || busy}
          onChange={(e) =>
            run(async () => {
              await call(api.PATCH("/admin/users/{user_id}", { ...path, body: { role: e.target.value as Role } }));
            })
          }
          className="w-40"
        >
          {ASSIGNABLE.map((r) => (
            <option key={r} value={r}>
              {ROLE_LABELS[r]}
            </option>
          ))}
        </Select>
      </td>
      <td className="py-2 pr-4">{user.totp_enabled ? <Badge tone="green">on</Badge> : <Badge>off</Badge>}</td>
      <td className="py-2 pr-4 text-xs text-zinc-500">{formatDate(user.last_login_at)}</td>
      <td className="py-2">
        <div className="flex flex-wrap gap-1">
          {!isSelf && (
            <Button
              variant="ghost"
              busy={busy}
              onClick={() =>
                run(async () => {
                  await call(api.PATCH("/admin/users/{user_id}", { ...path, body: { is_active: !user.is_active } }));
                })
              }
            >
              {user.is_active ? "Deactivate" : "Reactivate"}
            </Button>
          )}
          <Button
            variant="ghost"
            busy={busy}
            onClick={() =>
              run(async () => {
                const result = await call(api.POST("/admin/users/{user_id}/password-reset", path));
                onLink(result.url, result.emailed);
              })
            }
          >
            Reset password
          </Button>
          {!isSelf && user.totp_enabled && (
            <Button
              variant="ghost"
              busy={busy}
              onClick={() =>
                window.confirm(`Reset 2FA for ${user.name}? They will have to set it up again.`) &&
                run(async () => {
                  await call(api.POST("/admin/users/{user_id}/reset-2fa", path));
                })
              }
            >
              Reset 2FA
            </Button>
          )}
        </div>
      </td>
    </tr>
  );
}
