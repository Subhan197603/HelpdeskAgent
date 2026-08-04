import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { components } from "@fusion-helpdesk/api-client";
import {
  type ReactNode,
  type SyntheticEvent,
  useEffect,
  useMemo,
  useState,
} from "react";
import {
  Link,
  Navigate,
  Route,
  Routes,
  useLocation,
  useNavigate,
  useParams,
} from "react-router-dom";

import { AppShell, RequirePermission } from "./components/AppShell";
import { AttachmentUploader } from "./components/AttachmentUploader";
import { PriorityBadge, StatusBadge } from "./components/Badges";
import { PageHeader, Panel, SectionHeader } from "./components/Layout";
import {
  EmptyState,
  ErrorSummary,
  LoadingSkeleton,
  StatusPanel,
} from "./components/States";
import {
  QueueRow,
  TicketHeader,
  TicketListItem,
  TicketMetadata,
  TicketSidePanel,
} from "./components/Tickets";
import { newIdempotencyKey, sessionApiClient, unwrap } from "./lib/api";
import { beginLogin, completeLogin, sanitizeReturnTo } from "./lib/auth/oidc";
import { type Persona, sessionHome, useSession } from "./lib/session";

type FormField = components["schemas"]["FormFieldResponse"];
type RequestForm = components["schemas"]["RequestFormResponse"];
type Draft = components["schemas"]["DraftResponse"];
type FieldValue = string | string[] | boolean;

function RequireSession({ children }: { children: ReactNode }) {
  const { session } = useSession();
  const location = useLocation();
  if (session) return children;
  return (
    <Navigate replace state={{ returnTo: location.pathname }} to="/login" />
  );
}

export function LoginPage() {
  const { session, signIn, authConfiguration, reloadAuthConfiguration } =
    useSession();
  const navigate = useNavigate();
  const location = useLocation();
  const queryClient = useQueryClient();
  const [ssoError, setSsoError] = useState(false);
  const [ssoPending, setSsoPending] = useState(false);
  if (session) return <Navigate to={sessionHome(session)} />;
  const returnTo = sanitizeReturnTo(
    (location.state as { returnTo?: string } | null)?.returnTo,
  );
  const enter = (persona: Persona) => {
    queryClient.clear();
    signIn({
      persona,
      identity: persona === "analyst" ? "DEV/agent" : "DEV/customer",
    });
    navigate(persona === "analyst" ? "/agent/tickets" : "/portal");
  };
  const startSso = () => {
    if (!authConfiguration) return;
    setSsoError(false);
    setSsoPending(true);
    beginLogin(authConfiguration, returnTo).catch(() => {
      setSsoPending(false);
      setSsoError(true);
    });
  };
  return (
    <div className="login-page">
      <section className="login-panel" aria-labelledby="login-heading">
        <p className="eyebrow">Internal support, made clear</p>
        <h1 id="login-heading">How can we help today?</h1>
        <p>
          Browse configured services, submit a request, or continue work in the
          analyst workspace.
        </p>
        {authConfiguration === undefined && (
          <StatusPanel>Preparing sign-in…</StatusPanel>
        )}
        {authConfiguration === null && (
          <div role="alert">
            <p>The sign-in configuration could not be loaded.</p>
            <button
              className="button secondary"
              onClick={reloadAuthConfiguration}
              type="button"
            >
              Try again
            </button>
          </div>
        )}
        {authConfiguration && (
          <div className="login-actions">
            {authConfiguration.oidc_enabled && (
              <button
                className="button primary"
                disabled={ssoPending}
                onClick={startSso}
                type="button"
              >
                {ssoPending ? "Redirecting…" : "Sign in"}
              </button>
            )}
            {authConfiguration.developer_identity_enabled && (
              <>
                <button
                  className="button primary"
                  onClick={() => {
                    enter("employee");
                  }}
                  type="button"
                >
                  Continue as employee
                </button>
                <button
                  className="button secondary"
                  onClick={() => {
                    enter("analyst");
                  }}
                  type="button"
                >
                  Continue as analyst
                </button>
              </>
            )}
            {!authConfiguration.oidc_enabled &&
              !authConfiguration.developer_identity_enabled && (
                <p role="alert">
                  No sign-in method is configured. Contact your administrator.
                </p>
              )}
          </div>
        )}
        {ssoError && (
          <p role="alert">
            Sign-in could not start. Check your connection and try again.
          </p>
        )}
        {authConfiguration?.developer_identity_enabled && (
          <p className="development-note">Development identity mode</p>
        )}
      </section>
    </div>
  );
}

export function AuthCallbackPage() {
  const { authConfiguration, completeOidcSession } = useSession();
  const navigate = useNavigate();
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    if (!authConfiguration) return;
    const params = new URLSearchParams(window.location.search);
    let active = true;
    completeLogin(authConfiguration, params)
      .then(({ returnTo }) => {
        if (!active) return;
        completeOidcSession();
        navigate(returnTo, { replace: true });
      })
      .catch(() => {
        if (active) setFailed(true);
      });
    return () => {
      active = false;
    };
  }, [authConfiguration, completeOidcSession, navigate]);
  if (authConfiguration === null || failed) {
    return (
      <div className="login-page">
        <section className="login-panel" aria-labelledby="callback-heading">
          <h1 id="callback-heading">Sign-in could not complete</h1>
          <p role="alert">
            The sign-in response was rejected. Start again from the sign-in
            page.
          </p>
          <Link className="button primary" to="/login">
            Return to sign in
          </Link>
        </section>
      </div>
    );
  }
  return (
    <div className="login-page">
      <StatusPanel>Completing sign-in…</StatusPanel>
    </div>
  );
}

function PortalHome() {
  const client = useIdentityClient();
  const tickets = useQuery({
    queryKey: ["portal-recent-tickets"],
    queryFn: async () => unwrap(await client.GET("/api/v1/my/tickets")),
  });
  const projects = useQuery({
    queryKey: ["portal-service-projects"],
    queryFn: async () => unwrap(await client.GET("/api/v1/catalog/projects")),
  });
  return (
    <div className="page portal-dashboard">
      <section className="portal-hero" aria-labelledby="portal-title">
        <p className="eyebrow">Employee portal</p>
        <h1 id="portal-title">How can we help you?</h1>
        <p>Find the right service or track an existing support request.</p>
        <label className="portal-search">
          <span className="sr-only">Search help services</span>
          <input
            disabled
            placeholder="Search for services or support…"
            title="Search will be enabled in a future milestone"
          />
        </label>
        <div className="hero-actions">
          <Link className="button primary" to="/portal/catalog">
            Browse services
          </Link>
          <Link
            className="button secondary button--inverse"
            to="/portal/requests"
          >
            My tickets
          </Link>
        </div>
      </section>
      <section aria-labelledby="popular-services">
        <SectionHeader
          action={<Link to="/portal/catalog">View all services →</Link>}
          title="Popular services"
        />
        {projects.isPending && (
          <LoadingSkeleton label="Loading popular services" />
        )}
        {projects.error && <ErrorSummary error={projects.error} />}
        <div className="service-card-grid">
          {projects.data?.items.slice(0, 3).map((project) => (
            <Link
              className="service-card"
              key={project.id}
              to="/portal/catalog"
            >
              <span aria-hidden="true">{project.code.slice(0, 1)}</span>
              <div>
                <h3>{project.name}</h3>
                <p>
                  {project.description ?? "Browse available support requests."}
                </p>
              </div>
            </Link>
          ))}
        </div>
      </section>
      <Panel className="recent-tickets">
        <SectionHeader
          action={<Link to="/portal/requests">View all tickets →</Link>}
          title="Recent tickets"
        />
        {tickets.isPending && (
          <LoadingSkeleton label="Loading recent tickets" />
        )}
        {tickets.error && <ErrorSummary error={tickets.error} />}
        {tickets.data?.items.length === 0 && (
          <EmptyState
            description="Create a request from the service catalogue when you need help."
            title="No tickets yet"
          />
        )}
        {tickets.data?.items.slice(0, 5).map((ticket) => (
          <TicketListItem
            href={`/portal/requests/${ticket.key}`}
            key={ticket.id}
            priority={ticket.priority}
            status={ticket.status_name}
            summary={ticket.summary}
            ticketKey={ticket.key}
          />
        ))}
      </Panel>
    </div>
  );
}

function useIdentityClient() {
  const { session } = useSession();
  return useMemo(() => sessionApiClient(session), [session]);
}

function CataloguePage() {
  const client = useIdentityClient();
  const [projectId, setProjectId] = useState<string | null>(null);
  const projects = useQuery({
    queryKey: ["catalogue-projects"],
    queryFn: async () => unwrap(await client.GET("/api/v1/catalog/projects")),
  });
  useEffect(() => {
    if (!projectId && projects.data?.items[0])
      setProjectId(projects.data.items[0].id);
  }, [projectId, projects.data]);
  const requestTypes = useQuery({
    queryKey: ["request-types", projectId],
    enabled: Boolean(projectId),
    queryFn: async () => {
      if (!projectId) throw new Error("A catalogue project is required.");
      return unwrap(
        await client.GET(
          "/api/v1/catalog/projects/{project_id}/request-types",
          {
            params: { path: { project_id: projectId } },
          },
        ),
      );
    },
  });
  return (
    <div className="page">
      <p className="eyebrow">Service catalogue</p>
      <h1>What do you need help with?</h1>
      <p className="lede">
        Request forms are loaded from the currently published configuration.
      </p>
      {projects.isPending && (
        <StatusPanel>Loading service projects…</StatusPanel>
      )}
      {projects.error && <ErrorSummary error={projects.error} />}
      {projects.data?.items.length === 0 && (
        <StatusPanel>No services are available.</StatusPanel>
      )}
      {projects.data && projects.data.items.length > 0 && (
        <>
          <div
            className="project-tabs"
            role="tablist"
            aria-label="Service projects"
          >
            {projects.data.items.map((project) => (
              <button
                aria-selected={project.id === projectId}
                className={project.id === projectId ? "active" : ""}
                key={project.id}
                onClick={() => {
                  setProjectId(project.id);
                }}
                role="tab"
                type="button"
              >
                <span>{project.code}</span>
                {project.name}
              </button>
            ))}
          </div>
          {requestTypes.isPending && (
            <StatusPanel>Loading request types…</StatusPanel>
          )}
          {requestTypes.error && <ErrorSummary error={requestTypes.error} />}
          {requestTypes.data?.items.length === 0 && (
            <StatusPanel>
              No published request types are available for this service.
            </StatusPanel>
          )}
          <div className="card-grid">
            {requestTypes.data?.items.map((requestType) => (
              <Link
                className="request-card"
                key={requestType.id}
                to={`/portal/catalog/${requestType.id}`}
              >
                <span className="card-code">{requestType.work_type.name}</span>
                <h2>{requestType.name}</h2>
                <p>
                  {requestType.description ??
                    "Open the configured request form."}
                </p>
                <span className="card-link">Start request →</span>
              </Link>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

function conditionMatches(
  field: FormField,
  values: Record<string, FieldValue>,
): boolean {
  const condition = field.condition;
  if (!condition) return true;
  const predicates = condition.all ?? condition.any ?? [];
  const checks = predicates.map((predicate) => {
    const actual = values[predicate.field];
    if (predicate.operator === "is_empty")
      return actual === undefined || actual === "";
    if (predicate.operator === "is_not_empty")
      return actual !== undefined && actual !== "";
    if (predicate.operator === "equals") return actual === predicate.value;
    if (predicate.operator === "not_equals") return actual !== predicate.value;
    const expected = Array.isArray(predicate.value) ? predicate.value : [];
    return expected.includes(String(actual)) === (predicate.operator === "in");
  });
  return condition.all ? checks.every(Boolean) : checks.some(Boolean);
}

export function DynamicField({
  field,
  value,
  onChange,
}: {
  field: FormField;
  value: FieldValue | undefined;
  onChange: (value: FieldValue) => void;
}) {
  const id = `field-${field.field_code}`;
  const descriptionId = field.description ? `${id}-description` : undefined;
  const common = {
    id,
    name: field.field_code,
    required: field.required,
    "aria-describedby": descriptionId,
  };
  let control: ReactNode;
  if (field.data_type === "LONG_TEXT") {
    control = (
      <textarea
        {...common}
        value={String(value ?? "")}
        onChange={(event) => {
          onChange(event.target.value);
        }}
        rows={6}
      />
    );
  } else if (field.data_type === "SINGLE_SELECT") {
    control = (
      <select
        {...common}
        value={String(value ?? "")}
        onChange={(event) => {
          onChange(event.target.value);
        }}
      >
        <option value="">Select an option</option>
        {field.options.map((option) => (
          <option key={option.id} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    );
  } else if (field.data_type === "MULTI_SELECT") {
    control = (
      <select
        {...common}
        multiple
        value={Array.isArray(value) ? value : []}
        onChange={(event) => {
          onChange(
            Array.from(event.target.selectedOptions, (option) => option.value),
          );
        }}
      >
        {field.options.map((option) => (
          <option key={option.id} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    );
  } else if (field.data_type === "BOOLEAN") {
    control = (
      <input
        {...common}
        checked={Boolean(value)}
        onChange={(event) => {
          onChange(event.target.checked);
        }}
        type="checkbox"
      />
    );
  } else {
    const type =
      field.data_type === "NUMBER"
        ? "number"
        : field.data_type === "DATE"
          ? "date"
          : "text";
    control = (
      <input
        {...common}
        type={type}
        value={String(value ?? "")}
        onChange={(event) => {
          onChange(event.target.value);
        }}
      />
    );
  }
  return (
    <div
      className={`form-field ${field.data_type === "BOOLEAN" ? "checkbox-field" : ""}`}
    >
      <label htmlFor={id}>
        {field.label}
        {field.required && <span aria-hidden="true"> *</span>}
      </label>
      {field.description && <p id={descriptionId}>{field.description}</p>}
      {control}
    </div>
  );
}

function RequestFormPage() {
  const { requestTypeId = "" } = useParams();
  const client = useIdentityClient();
  const navigate = useNavigate();
  const [values, setValues] = useState<Record<string, FieldValue>>({});
  const [impact, setImpact] = useState("LIMITED");
  const [urgency, setUrgency] = useState("NORMAL");
  const form = useQuery({
    queryKey: ["request-form", requestTypeId],
    queryFn: async () =>
      unwrap(
        await client.GET(
          "/api/v1/catalog/request-types/{request_type_id}/form",
          { params: { path: { request_type_id: requestTypeId } } },
        ),
      ),
  });
  const createDraft = useMutation({
    mutationFn: async (configuration: RequestForm) => {
      const customFields = configuration.fields
        .filter(
          (field) => !["summary", "description"].includes(field.field_code),
        )
        .filter(
          (field) =>
            values[field.field_code] !== undefined &&
            values[field.field_code] !== "",
        )
        .map((field) => ({
          field_code: field.field_code,
          value: values[field.field_code],
        }));
      const created = unwrap(
        await client.POST("/api/v1/ticket-drafts", {
          body: {
            request_type_id: configuration.request_type_id,
            summary: String(values.summary ?? ""),
            description: values.description ? String(values.description) : null,
            impact,
            urgency,
            custom_fields: customFields,
            service_node_id: null,
            application_environment_id: null,
            requested_for_user_id: null,
          },
        }),
      );
      return unwrap(
        await client.POST("/api/v1/ticket-drafts/{draft_id}/validate", {
          params: {
            path: { draft_id: created.id },
            header: { "If-Match": String(created.row_version) },
          },
          body: { row_version: created.row_version },
        }),
      );
    },
    onSuccess: (validated) => {
      navigate(`/portal/drafts/${validated.draft.id}/review`);
    },
  });
  const submit = (event: SyntheticEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (form.data) createDraft.mutate(form.data);
  };
  return (
    <div className="page narrow-page request-form-page">
      <Link className="back-link" to="/portal/catalog">
        ← Back to catalogue
      </Link>
      {form.isPending && (
        <StatusPanel>Loading the published request form…</StatusPanel>
      )}
      {form.error && <ErrorSummary error={form.error} />}
      {createDraft.error && <ErrorSummary error={createDraft.error} />}
      {form.data && (
        <form onSubmit={submit} noValidate>
          <p className="eyebrow">{form.data.project.name}</p>
          <h1>{form.data.name}</h1>
          <p className="lede">{form.data.description}</p>
          <p className="version-note">
            Form version {form.data.version_number}
          </p>
          {form.data.fields
            .filter((field) => conditionMatches(field, values))
            .map((field) => (
              <DynamicField
                key={field.field_id}
                field={field}
                value={values[field.field_code]}
                onChange={(value) => {
                  setValues((current) => ({
                    ...current,
                    [field.field_code]: value,
                  }));
                }}
              />
            ))}
          <div className="field-row">
            <div className="form-field">
              <label htmlFor="impact">Impact</label>
              <select
                id="impact"
                value={impact}
                onChange={(event) => {
                  setImpact(event.target.value);
                }}
              >
                <option value="LIMITED">One person</option>
                <option value="MODERATE">One team</option>
                <option value="SIGNIFICANT">Several teams</option>
                <option value="EXTENSIVE">Organization-wide</option>
              </select>
            </div>
            <div className="form-field">
              <label htmlFor="urgency">Urgency</label>
              <select
                id="urgency"
                value={urgency}
                onChange={(event) => {
                  setUrgency(event.target.value);
                }}
              >
                <option value="LOW">Planning</option>
                <option value="NORMAL">Workaround available</option>
                <option value="HIGH">Material degradation</option>
                <option value="IMMEDIATE">Work stopped</option>
              </select>
            </div>
          </div>
          <button
            className="button primary"
            disabled={createDraft.isPending}
            type="submit"
          >
            {createDraft.isPending ? "Validating…" : "Review request"}
          </button>
        </form>
      )}
    </div>
  );
}

function DraftReviewPage() {
  const { draftId = "" } = useParams();
  const client = useIdentityClient();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const draft = useQuery({
    queryKey: ["draft", draftId],
    queryFn: async () =>
      unwrap(
        await client.GET("/api/v1/ticket-drafts/{draft_id}", {
          params: { path: { draft_id: draftId } },
        }),
      ),
  });
  const [editing, setEditing] = useState(false);
  const [summary, setSummary] = useState("");
  useEffect(() => {
    if (draft.data) setSummary(draft.data.summary);
  }, [draft.data]);
  const update = useMutation({
    mutationFn: async (current: Draft) =>
      unwrap(
        await client.PATCH("/api/v1/ticket-drafts/{draft_id}", {
          params: {
            path: { draft_id: draftId },
            header: { "If-Match": String(current.row_version) },
          },
          body: { row_version: current.row_version, summary },
        }),
      ),
    onSuccess: async (updated) => {
      const validated = unwrap(
        await client.POST("/api/v1/ticket-drafts/{draft_id}/validate", {
          params: {
            path: { draft_id: draftId },
            header: { "If-Match": String(updated.row_version) },
          },
          body: { row_version: updated.row_version },
        }),
      );
      queryClient.setQueryData(["draft", draftId], validated.draft);
      setEditing(false);
    },
  });
  const confirm = useMutation({
    mutationFn: async (current: Draft) =>
      unwrap(
        await client.POST("/api/v1/ticket-drafts/{draft_id}/submit", {
          params: {
            path: { draft_id: draftId },
            header: {
              "Idempotency-Key": newIdempotencyKey("portal-submit"),
              "If-Match": String(current.row_version),
            },
          },
          body: { row_version: current.row_version },
        }),
      ),
    onSuccess: (ticket) => {
      navigate(`/portal/requests/${ticket.key}`);
    },
  });
  return (
    <div className="page narrow-page">
      <p className="eyebrow">Confirm submission</p>
      <h1>Review your request</h1>
      <p className="lede">
        No permanent ticket exists until you choose “Confirm and submit”.
      </p>
      {draft.isPending && <StatusPanel>Loading draft…</StatusPanel>}
      {draft.error && <ErrorSummary error={draft.error} />}
      {(update.error ?? confirm.error) && (
        <ErrorSummary error={update.error ?? confirm.error} />
      )}
      {draft.data && (
        <section className="review-card">
          {editing ? (
            <form
              onSubmit={(event) => {
                event.preventDefault();
                update.mutate(draft.data);
              }}
            >
              <div className="form-field">
                <label htmlFor="edit-summary">Summary</label>
                <input
                  id="edit-summary"
                  value={summary}
                  onChange={(event) => {
                    setSummary(event.target.value);
                  }}
                  required
                />
              </div>
              <button className="button primary" type="submit">
                Save and revalidate
              </button>
              <button
                className="button secondary"
                onClick={() => {
                  setEditing(false);
                }}
                type="button"
              >
                Cancel
              </button>
            </form>
          ) : (
            <>
              <dl className="details">
                <div>
                  <dt>Summary</dt>
                  <dd>{draft.data.summary}</dd>
                </div>
                <div>
                  <dt>Description</dt>
                  <dd>{draft.data.description ?? "Not supplied"}</dd>
                </div>
                <div>
                  <dt>Impact / urgency</dt>
                  <dd>
                    {draft.data.impact} / {draft.data.urgency}
                  </dd>
                </div>
                <div>
                  <dt>Calculated priority</dt>
                  <dd>{draft.data.priority}</dd>
                </div>
              </dl>
              <button
                className="button secondary"
                onClick={() => {
                  setEditing(true);
                }}
                type="button"
              >
                Edit summary
              </button>
              <button
                className="button primary"
                disabled={confirm.isPending}
                onClick={() => {
                  confirm.mutate(draft.data);
                }}
                type="button"
              >
                {confirm.isPending ? "Submitting…" : "Confirm and submit"}
              </button>
            </>
          )}
        </section>
      )}
    </div>
  );
}

function TicketListPage({ analyst = false }: { analyst?: boolean }) {
  const client = useIdentityClient();
  const path = analyst
    ? ("/api/v1/agent/tickets" as const)
    : ("/api/v1/my/tickets" as const);
  const tickets = useQuery({
    queryKey: [analyst ? "agent-tickets" : "my-tickets"],
    queryFn: async () => unwrap(await client.GET(path)),
  });
  return (
    <div className="page">
      <PageHeader
        description={
          analyst
            ? "Review tickets visible to your support groups."
            : "Track requests and public support updates."
        }
        eyebrow={analyst ? "Analyst workspace" : "Employee portal"}
        title={analyst ? "Tickets needing attention" : "My tickets"}
      />
      {tickets.isPending && <StatusPanel>Loading tickets…</StatusPanel>}
      {tickets.error && <ErrorSummary error={tickets.error} />}
      {tickets.data?.items.length === 0 && (
        <EmptyState
          description={
            analyst
              ? "No accessible tickets are waiting."
              : "You have no requests yet."
          }
        />
      )}
      <div className="ticket-list">
        {tickets.data?.items.map((ticket) => (
          <TicketListItem
            href={
              analyst
                ? `/agent/tickets/${ticket.key}`
                : `/portal/requests/${ticket.key}`
            }
            key={ticket.id}
            metadata={ticket.request_type_name}
            priority={ticket.priority}
            status={ticket.status_name}
            summary={ticket.summary}
            ticketKey={ticket.key}
          />
        ))}
      </div>
    </div>
  );
}

function AgentQueuePage() {
  const client = useIdentityClient();
  const [queueId, setQueueId] = useState<string | null>(null);
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [cursor, setCursor] = useState<string | null>(null);
  const queues = useQuery({
    queryKey: ["agent-queues"],
    queryFn: async () => unwrap(await client.GET("/api/v1/agent/queues")),
  });
  useEffect(() => {
    if (!queueId && queues.data?.items[0]) setQueueId(queues.data.items[0].id);
  }, [queueId, queues.data]);
  const tickets = useQuery({
    queryKey: ["agent-queue-tickets", queueId, cursor, search],
    enabled: Boolean(queueId),
    queryFn: async () => {
      if (!queueId) throw new Error("Select an analyst queue.");
      return unwrap(
        await client.GET("/api/v1/agent/queues/{queue_id}/tickets", {
          params: {
            path: { queue_id: queueId },
            query: {
              cursor: cursor ?? undefined,
              search: search || undefined,
            },
          },
        }),
      );
    },
  });
  const selected = queues.data?.items.find((queue) => queue.id === queueId);
  return (
    <div className="page analyst-queues">
      <PageHeader
        description="Prioritized work available to your support groups."
        eyebrow="Analyst workspace"
        title="My queues"
      />
      {queues.isPending && <StatusPanel>Loading queues…</StatusPanel>}
      {queues.error && <ErrorSummary error={queues.error} />}
      {queues.data?.items.length === 0 && (
        <StatusPanel>No queues are available for your groups.</StatusPanel>
      )}
      {queues.data && queues.data.items.length > 0 && (
        <div className="queue-layout">
          <nav aria-label="Analyst queues" className="queue-navigation">
            {queues.data.items.map((queue) => (
              <button
                aria-current={queue.id === queueId ? "page" : undefined}
                className={queue.id === queueId ? "active" : ""}
                key={queue.id}
                onClick={() => {
                  setQueueId(queue.id);
                  setCursor(null);
                }}
                type="button"
              >
                <strong>{queue.name}</strong>
                <small>{queue.project_code}</small>
              </button>
            ))}
          </nav>
          <section aria-labelledby="queue-heading" className="queue-results">
            <h2 id="queue-heading">{selected?.name}</h2>
            {selected?.description && <p>{selected.description}</p>}
            <form
              className="queue-search"
              onSubmit={(event) => {
                event.preventDefault();
                setSearch(searchInput.trim());
                setCursor(null);
              }}
              role="search"
            >
              <label htmlFor="queue-search">Search ticket key or summary</label>
              <div>
                <input
                  id="queue-search"
                  maxLength={100}
                  onChange={(event) => {
                    setSearchInput(event.target.value);
                  }}
                  value={searchInput}
                />
                <button className="button secondary" type="submit">
                  Search
                </button>
              </div>
            </form>
            {tickets.isPending && (
              <StatusPanel>Loading queue tickets…</StatusPanel>
            )}
            {tickets.error && <ErrorSummary error={tickets.error} />}
            {tickets.data?.items.length === 0 && (
              <StatusPanel>No tickets match this queue.</StatusPanel>
            )}
            <div className="ticket-list">
              {tickets.data?.items.map((ticket) => (
                <QueueRow
                  href={`/agent/tickets/${ticket.key}`}
                  key={ticket.id}
                  priority={ticket.priority}
                  status={ticket.status_name}
                  summary={ticket.summary}
                  ticketKey={ticket.key}
                  metadata={`${ticket.assignment_group_name ?? "Unassigned"}${ticket.assignee_name ? ` · ${ticket.assignee_name}` : ""}`}
                />
              ))}
            </div>
            {tickets.data?.next_cursor && (
              <button
                className="button secondary"
                onClick={() => {
                  setCursor(tickets.data.next_cursor ?? null);
                }}
                type="button"
              >
                Next page
              </button>
            )}
          </section>
        </div>
      )}
    </div>
  );
}

function TicketDetailPage({ analyst = false }: { analyst?: boolean }) {
  const { ticketKey = "" } = useParams();
  const client = useIdentityClient();
  const queryClient = useQueryClient();
  const path = analyst
    ? ("/api/v1/agent/tickets/{ticket_key}" as const)
    : ("/api/v1/tickets/{ticket_key}" as const);
  const queryKey = [analyst ? "agent-ticket" : "ticket", ticketKey];
  const ticket = useQuery({
    queryKey,
    queryFn: async () =>
      unwrap(
        await client.GET(path, { params: { path: { ticket_key: ticketKey } } }),
      ),
  });
  const timelinePath = analyst
    ? ("/api/v1/agent/tickets/{ticket_key}/timeline" as const)
    : ("/api/v1/tickets/{ticket_key}/timeline" as const);
  const timelineKey = [analyst ? "agent-timeline" : "timeline", ticketKey];
  const timeline = useQuery({
    queryKey: timelineKey,
    queryFn: async () =>
      unwrap(
        await client.GET(timelinePath, {
          params: { path: { ticket_key: ticketKey } },
        }),
      ),
  });
  const [comment, setComment] = useState("");
  const [visibility, setVisibility] = useState<"PUBLIC" | "INTERNAL">("PUBLIC");
  const addComment = useMutation({
    mutationFn: async () => {
      if (analyst) {
        return unwrap(
          await client.POST("/api/v1/agent/tickets/{ticket_key}/comments", {
            params: {
              path: { ticket_key: ticketKey },
              header: {
                "Idempotency-Key": newIdempotencyKey("analyst-comment"),
              },
            },
            body: { body: comment, visibility },
          }),
        );
      }
      return unwrap(
        await client.POST("/api/v1/tickets/{ticket_key}/comments", {
          params: {
            path: { ticket_key: ticketKey },
            header: { "Idempotency-Key": newIdempotencyKey("public-comment") },
          },
          body: { body: comment },
        }),
      );
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey });
      void queryClient.invalidateQueries({ queryKey: timelineKey });
      setComment("");
    },
  });
  return (
    <div className="page ticket-page">
      {ticket.isPending && <StatusPanel>Loading ticket…</StatusPanel>}
      {ticket.error && <ErrorSummary error={ticket.error} />}
      {addComment.error && <ErrorSummary error={addComment.error} />}
      {ticket.data && (
        <>
          <Link
            className="back-link"
            to={analyst ? "/agent/tickets" : "/portal/requests"}
          >
            ← Back to tickets
          </Link>
          <TicketHeader
            priority={ticket.data.priority}
            status={ticket.data.status_name}
            summary={ticket.data.summary}
            ticketKey={ticket.data.key}
          />
          <div className="ticket-workspace">
            <div className="ticket-workspace__main">
              <section aria-labelledby="activity-heading" className="activity">
                <h2 id="activity-heading">
                  {analyst ? "Activity timeline" : "Public activity"}
                </h2>
                {timeline.isPending && (
                  <StatusPanel>Loading activity…</StatusPanel>
                )}
                {timeline.error && <ErrorSummary error={timeline.error} />}
                {timeline.data?.items.length === 0 ? (
                  <StatusPanel>No activity yet.</StatusPanel>
                ) : (
                  <ol>
                    {timeline.data?.items.map((item) => (
                      <li key={item.id}>
                        <div>
                          <strong>{item.actor_name ?? item.type}</strong>
                          {analyst && (
                            <span
                              className={`visibility ${item.classification.toLowerCase()}`}
                            >
                              {item.classification}
                            </span>
                          )}
                          <time dateTime={item.created_at}>
                            {new Date(item.created_at).toLocaleString()}
                          </time>
                        </div>
                        <p>{item.body ?? item.type.replaceAll("_", " ")}</p>
                      </li>
                    ))}
                  </ol>
                )}
                <form
                  onSubmit={(event) => {
                    event.preventDefault();
                    addComment.mutate();
                  }}
                >
                  <div className="form-field">
                    <label htmlFor="public-comment">
                      {analyst ? "Add an update" : "Add a public comment"}
                    </label>
                    <p id="comment-help">
                      {visibility === "PUBLIC"
                        ? "This comment is visible to the employee and support analysts."
                        : "This internal note is visible only to authorized analysts."}
                    </p>
                    {analyst && (
                      <select
                        aria-label="Comment visibility"
                        onChange={(event) => {
                          setVisibility(
                            event.target.value as "PUBLIC" | "INTERNAL",
                          );
                        }}
                        value={visibility}
                      >
                        <option value="PUBLIC">Public comment</option>
                        <option value="INTERNAL">Internal note</option>
                      </select>
                    )}
                    <textarea
                      aria-describedby="comment-help"
                      id="public-comment"
                      value={comment}
                      onChange={(event) => {
                        setComment(event.target.value);
                      }}
                      required
                      rows={4}
                    />
                  </div>
                  <button
                    className="button primary"
                    disabled={addComment.isPending}
                    type="submit"
                  >
                    {addComment.isPending
                      ? "Posting…"
                      : visibility === "INTERNAL"
                        ? "Post internal note"
                        : "Post public comment"}
                  </button>
                </form>
              </section>
              <AttachmentUploader
                analyst={analyst}
                client={client}
                ticketKey={ticketKey}
              />
            </div>
            <TicketSidePanel>
              <TicketMetadata
                items={[
                  {
                    label: "Status",
                    value: <StatusBadge status={ticket.data.status_name} />,
                  },
                  {
                    label: "Priority",
                    value: <PriorityBadge priority={ticket.data.priority} />,
                  },
                  {
                    label: "Request type",
                    value: ticket.data.request_type_name,
                  },
                  { label: "Reporter", value: ticket.data.reporter_name },
                  {
                    label: "Created",
                    value: new Date(ticket.data.created_at).toLocaleString(),
                  },
                ]}
              />
            </TicketSidePanel>
          </div>
        </>
      )}
    </div>
  );
}

export function App() {
  return (
    <AppShell>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/auth/callback" element={<AuthCallbackPage />} />
        <Route path="/" element={<Navigate to="/portal" replace />} />
        <Route
          path="/portal"
          element={
            <RequireSession>
              <RequirePermission permission="TICKET_READ_OWN">
                <PortalHome />
              </RequirePermission>
            </RequireSession>
          }
        />
        <Route
          path="/portal/catalog"
          element={
            <RequireSession>
              <RequirePermission permission="CATALOG_PROJECT_LIST">
                <CataloguePage />
              </RequirePermission>
            </RequireSession>
          }
        />
        <Route
          path="/portal/catalog/:requestTypeId"
          element={
            <RequireSession>
              <RequirePermission permission="TICKET_DRAFT_CREATE">
                <RequestFormPage />
              </RequirePermission>
            </RequireSession>
          }
        />
        <Route
          path="/portal/drafts/:draftId/review"
          element={
            <RequireSession>
              <DraftReviewPage />
            </RequireSession>
          }
        />
        <Route
          path="/portal/requests"
          element={
            <RequireSession>
              <TicketListPage />
            </RequireSession>
          }
        />
        <Route
          path="/portal/requests/:ticketKey"
          element={
            <RequireSession>
              <TicketDetailPage />
            </RequireSession>
          }
        />
        <Route
          path="/agent/tickets"
          element={
            <RequireSession>
              <RequirePermission permission="TICKET_ANALYST_READ">
                <AgentQueuePage />
              </RequirePermission>
            </RequireSession>
          }
        />
        <Route
          path="/agent/tickets/:ticketKey"
          element={
            <RequireSession>
              <RequirePermission permission="TICKET_ANALYST_READ">
                <TicketDetailPage analyst />
              </RequirePermission>
            </RequireSession>
          }
        />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </AppShell>
  );
}
