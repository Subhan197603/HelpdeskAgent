import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { components, paths } from "@fusion-helpdesk/api-client";
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
  useSearchParams,
} from "react-router-dom";

import { humanizeCode, OutcomeBadge } from "./components/Admin";
import {
  AppShell,
  RequirePermission,
  useCurrentIdentity,
} from "./components/AppShell";
import { Pagination } from "./components/DataTable";
import { AttachmentUploader } from "./components/AttachmentUploader";
import {
  HealthIndicator,
  PriorityBadge,
  SlaBadge,
  StatusBadge,
} from "./components/Badges";
import { Button } from "./components/Button";
import { ActivityFeed, DonutChart, formatDelta } from "./components/Dashboard";
import { SearchField } from "./components/SearchField";
import { Tabs } from "./components/Tabs";
import {
  ArticleCard,
  documentTypeLabel,
  groupEvidenceByDocument,
  highlightMatches,
} from "./components/Knowledge";
import {
  AttachmentList,
  headlineSla,
  slaPresentation,
  TransitionMenu,
} from "./components/TicketDetail";
import {
  Breadcrumbs,
  MetadataGrid,
  PageHeader,
  Panel,
  SectionHeader,
  StatCard,
} from "./components/Layout";
import {
  EmptyState,
  ErrorSummary,
  LoadingSkeleton,
  StatusPanel,
} from "./components/States";
import {
  ParticipantCard,
  QueueRow,
  TicketHeader,
  TicketListItem,
  TicketMetadata,
  TicketSidePanel,
} from "./components/Tickets";
import {
  ApiProblem,
  newIdempotencyKey,
  sessionApiClient,
  unwrap,
} from "./lib/api";
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
  const enterAdministrator = () => {
    queryClient.clear();
    signIn({ persona: "analyst", identity: "DEV/platform-admin" });
    navigate("/agent/tickets");
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
            <Button onClick={reloadAuthConfiguration} variant="secondary">
              Try again
            </Button>
          </div>
        )}
        {authConfiguration && (
          <div className="login-actions">
            {authConfiguration.oidc_enabled && (
              <Button disabled={ssoPending} onClick={startSso}>
                {ssoPending ? "Redirecting…" : "Sign in"}
              </Button>
            )}
            {authConfiguration.developer_identity_enabled && (
              <>
                <Button
                  onClick={() => {
                    enter("employee");
                  }}
                >
                  Continue as employee
                </Button>
                <Button
                  onClick={() => {
                    enter("analyst");
                  }}
                  variant="secondary"
                >
                  Continue as analyst
                </Button>
                <Button onClick={enterAdministrator} variant="secondary">
                  Continue as administrator
                </Button>
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
          <Button to="/login">Return to sign in</Button>
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
        <SearchField
          className="portal-search"
          disabled
          label="Search help services"
          placeholder="Search for services or support…"
          title="Search will be enabled in a future milestone"
          withIcon={false}
        />
        <div className="hero-actions">
          <Button to="/portal/catalog">Browse services</Button>
          <Button to="/portal/requests" variant="inverse">
            My tickets
          </Button>
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
          <Tabs
            activeId={projectId ?? ""}
            items={projects.data.items.map((project) => ({
              badge: project.code,
              id: project.id,
              label: project.name,
            }))}
            label="Service projects"
            onChange={setProjectId}
          />
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
          <Button disabled={createDraft.isPending} type="submit">
            {createDraft.isPending ? "Validating…" : "Review request"}
          </Button>
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
              <Button type="submit">Save and revalidate</Button>
              <Button
                onClick={() => {
                  setEditing(false);
                }}
                variant="secondary"
              >
                Cancel
              </Button>
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
              <Button
                onClick={() => {
                  setEditing(true);
                }}
                variant="secondary"
              >
                Edit summary
              </Button>
              <Button
                disabled={confirm.isPending}
                onClick={() => {
                  confirm.mutate(draft.data);
                }}
              >
                {confirm.isPending ? "Submitting…" : "Confirm and submit"}
              </Button>
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

function AnalystDashboardPage() {
  const client = useIdentityClient();
  const dashboard = useQuery({
    queryKey: ["agent-dashboard"],
    queryFn: async () => unwrap(await client.GET("/api/v1/agent/dashboard")),
    staleTime: 30_000,
  });
  const primaryQueueId = dashboard.data?.primary_queue?.id;
  const queueTickets = useQuery({
    enabled: Boolean(primaryQueueId),
    queryKey: ["agent-dashboard-queue", primaryQueueId],
    queryFn: async () =>
      unwrap(
        await client.GET("/api/v1/agent/queues/{queue_id}/tickets", {
          params: {
            path: { queue_id: primaryQueueId ?? "" },
            query: { limit: 5 },
          },
        }),
      ),
    staleTime: 30_000,
  });
  if (dashboard.isPending)
    return (
      <div className="page">
        <LoadingSkeleton label="Loading dashboard" lines={6} />
      </div>
    );
  if (dashboard.error)
    return (
      <div className="page">
        <ErrorSummary error={dashboard.error} />
      </div>
    );
  const data = dashboard.data;
  const counts = data.counts;
  const compliance =
    data.sla_compliance_week.met + data.sla_compliance_week.breached > 0
      ? Math.round(
          (data.sla_compliance_week.met /
            (data.sla_compliance_week.met +
              data.sla_compliance_week.breached)) *
            100,
        )
      : null;
  return (
    <div className="page dashboard-page">
      <PageHeader
        description="Overview of helpdesk activity"
        title="Dashboard"
      />
      <div className="stat-grid">
        <StatCard label="Open Tickets" value={counts.open_now} />
        <StatCard
          detail={formatDelta(
            counts.new_today,
            counts.new_yesterday_same_elapsed_window,
          )}
          label="New Today"
          value={counts.new_today}
        />
        <StatCard label="SLA Breached" value={counts.sla_breached_open} />
        <StatCard label="Due Today" value={counts.due_today} />
        <StatCard
          detail={formatDelta(
            counts.resolved_today,
            counts.resolved_yesterday_same_elapsed_window,
          )}
          label="Resolved Today"
          value={counts.resolved_today}
        />
      </div>
      <div className="dashboard-panels">
        <Panel title="Tickets by Status">
          <DonutChart
            label="Open tickets by status"
            slices={data.status_distribution.map((slice) => ({
              label: slice.status_name,
              value: slice.count,
            }))}
          />
        </Panel>
        <Panel title="SLA Compliance (This Week)">
          <DonutChart
            centerText={
              compliance === null ? undefined : `${String(compliance)}%`
            }
            label="SLA compliance this week"
            slices={[
              { label: "Met", value: data.sla_compliance_week.met },
              { label: "Breached", value: data.sla_compliance_week.breached },
            ]}
          />
        </Panel>
        <Panel title="Recent Activity">
          <ActivityFeed items={data.recent_activity} />
        </Panel>
      </div>
      <div className="dashboard-lower">
        <Panel
          title={
            data.primary_queue
              ? `My Queue — ${data.primary_queue.name}`
              : "My Queue"
          }
        >
          {!data.primary_queue && (
            <EmptyState description="No queues are available for your groups." />
          )}
          {data.primary_queue && queueTickets.isPending && (
            <LoadingSkeleton label="Loading queue tickets" />
          )}
          {data.primary_queue && queueTickets.error && (
            <ErrorSummary error={queueTickets.error} />
          )}
          {queueTickets.data?.items.length === 0 && (
            <EmptyState description="No tickets in this queue right now." />
          )}
          {queueTickets.data && queueTickets.data.items.length > 0 && (
            <div className="ticket-list">
              {queueTickets.data.items.map((ticket) => (
                <QueueRow
                  href={`/agent/tickets/${ticket.key}`}
                  key={ticket.id}
                  metadata={ticket.reporter_name}
                  priority={ticket.priority}
                  status={ticket.status_name}
                  summary={ticket.summary}
                  ticketKey={ticket.key}
                />
              ))}
            </div>
          )}
          <p className="dashboard-link">
            <Link to="/agent/tickets">View full queue →</Link>
          </p>
        </Panel>
        <Panel title="Knowledge Usage">
          <EmptyState
            description="Article usage metrics arrive with the knowledge milestone."
            title="Not available yet"
          />
        </Panel>
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
                <Button type="submit" variant="secondary">
                  Search
                </Button>
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
              <Button
                onClick={() => {
                  setCursor(tickets.data.next_cursor ?? null);
                }}
                variant="secondary"
              >
                Next page
              </Button>
            )}
          </section>
        </div>
      )}
    </div>
  );
}

const DETAIL_TABS = [
  { id: "overview", label: "Overview" },
  { id: "activity", label: "Activity" },
  { id: "attachments", label: "Attachments" },
  { id: "participants", label: "Participants" },
  { id: "worklog", label: "Work Log" },
] as const;
type DetailTab = (typeof DETAIL_TABS)[number]["id"];

function AnalystTicketDetailPage() {
  const { ticketKey = "" } = useParams();
  const client = useIdentityClient();
  const queryClient = useQueryClient();
  const identity = useCurrentIdentity();
  const [searchParams, setSearchParams] = useSearchParams();
  const requested = searchParams.get("tab") ?? "overview";
  const tab: DetailTab = DETAIL_TABS.some((item) => item.id === requested)
    ? (requested as DetailTab)
    : "overview";
  const canTransition =
    identity?.permission_codes.includes("TICKET_TRANSITION") ?? false;
  const canAssign =
    identity?.permission_codes.includes("TICKET_ASSIGN_MANUAL") ?? false;
  const ticketQueryKey = ["agent-ticket", ticketKey];
  const ticket = useQuery({
    queryKey: ticketQueryKey,
    queryFn: async () =>
      unwrap(
        await client.GET("/api/v1/agent/tickets/{ticket_key}", {
          params: { path: { ticket_key: ticketKey } },
        }),
      ),
  });
  const timelineKey = ["agent-timeline", ticketKey];
  const timeline = useQuery({
    queryKey: timelineKey,
    queryFn: async () =>
      unwrap(
        await client.GET("/api/v1/agent/tickets/{ticket_key}/timeline", {
          params: { path: { ticket_key: ticketKey } },
        }),
      ),
  });
  const transitionsKey = ["agent-transitions", ticketKey];
  const transitions = useQuery({
    enabled: canTransition,
    queryKey: transitionsKey,
    queryFn: async () =>
      unwrap(
        await client.GET("/api/v1/agent/tickets/{ticket_key}/transitions", {
          params: { path: { ticket_key: ticketKey } },
        }),
      ),
  });
  const attachmentsKey = ["agent-attachments", ticketKey];
  const attachments = useQuery({
    enabled: tab === "attachments",
    queryKey: attachmentsKey,
    queryFn: async () =>
      unwrap(
        await client.GET("/api/v1/agent/tickets/{ticket_key}/attachments", {
          params: { path: { ticket_key: ticketKey } },
        }),
      ),
  });
  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ticketQueryKey });
    void queryClient.invalidateQueries({ queryKey: timelineKey });
    void queryClient.invalidateQueries({ queryKey: transitionsKey });
  };
  const transition = useMutation({
    mutationFn: async (transitionCode: string) => {
      const rowVersion = transitions.data?.row_version;
      if (rowVersion === undefined)
        throw new ApiProblem(409, "Transition state is stale. Reload first.");
      return unwrap(
        await client.POST("/api/v1/agent/tickets/{ticket_key}/transitions", {
          params: {
            path: { ticket_key: ticketKey },
            header: { "Idempotency-Key": newIdempotencyKey("transition") },
          },
          body: { transition_code: transitionCode, row_version: rowVersion },
        }),
      );
    },
    onSuccess: invalidate,
    onError: invalidate,
  });
  const [assignOpen, setAssignOpen] = useState(false);
  const [assignGroup, setAssignGroup] = useState("");
  const [assignToMe, setAssignToMe] = useState(false);
  const [assignReason, setAssignReason] = useState("");
  const assign = useMutation({
    mutationFn: async () => {
      const rowVersion = ticket.data?.row_version;
      if (rowVersion === undefined)
        throw new ApiProblem(409, "Ticket state is stale. Reload first.");
      return unwrap(
        await client.POST("/api/v1/agent/tickets/{ticket_key}/assignment", {
          params: {
            path: { ticket_key: ticketKey },
            header: { "Idempotency-Key": newIdempotencyKey("assignment") },
          },
          body: {
            assignment_group_id: assignGroup,
            assignee_user_id:
              assignToMe && identity ? identity.user_id : undefined,
            reason: assignReason,
            row_version: rowVersion,
          },
        }),
      );
    },
    onSuccess: () => {
      setAssignOpen(false);
      setAssignReason("");
      invalidate();
    },
  });
  const download = useMutation({
    mutationFn: async (attachmentId: string) =>
      unwrap(
        await client.POST("/api/v1/attachments/{attachment_id}/download", {
          params: { path: { attachment_id: attachmentId } },
        }),
      ),
    onSuccess: (result) => {
      window.open(result.download_url, "_blank", "noopener");
    },
  });
  const [comment, setComment] = useState("");
  const [visibility, setVisibility] = useState<"PUBLIC" | "INTERNAL">("PUBLIC");
  const addComment = useMutation({
    mutationFn: async () =>
      unwrap(
        await client.POST("/api/v1/agent/tickets/{ticket_key}/comments", {
          params: {
            path: { ticket_key: ticketKey },
            header: { "Idempotency-Key": newIdempotencyKey("analyst-comment") },
          },
          body: { body: comment, visibility },
        }),
      ),
    onSuccess: () => {
      setComment("");
      invalidate();
    },
  });
  if (ticket.isPending)
    return (
      <div className="page">
        <LoadingSkeleton label="Loading ticket" lines={6} />
      </div>
    );
  if (ticket.error)
    return (
      <div className="page">
        <ErrorSummary error={ticket.error} />
      </div>
    );
  const data = ticket.data;
  const slas = data.slas ?? [];
  const chipSla = headlineSla(slas);
  const statusHistory =
    timeline.data?.items
      .filter((item) => item.type === "STATUS_CHANGED")
      .slice(0, 5) ?? [];
  const supportGroups = identity?.support_group_ids ?? [];
  return (
    <div className="page ticket-page">
      <Breadcrumbs
        items={[
          { label: "Tickets", to: "/agent/tickets" },
          { label: data.key },
        ]}
      />
      <header className="detail-header">
        <div className="detail-header__badges">
          <span className="ticket-key">{data.key}</span>
          <StatusBadge status={data.status_name} />
          <PriorityBadge priority={data.priority} />
          {chipSla && (
            <SlaBadge
              label={`SLA ${slaPresentation(chipSla).label}`}
              state={
                slaPresentation(chipSla).label.toLowerCase() as
                  "breached" | "met" | "paused" | "running"
              }
            />
          )}
        </div>
        <div className="detail-header__title">
          <h1>{data.summary}</h1>
          <div className="detail-header__actions">
            {canAssign && (
              <Button
                onClick={() => {
                  setAssignOpen(true);
                }}
                variant="secondary"
              >
                Assign
              </Button>
            )}
            {canTransition && (
              <TransitionMenu
                onSelect={(code) => {
                  transition.mutate(code);
                }}
                pending={transition.isPending}
                transitions={transitions.data?.transitions ?? []}
              />
            )}
          </div>
        </div>
      </header>
      {(transition.error ?? assign.error ?? addComment.error) && (
        <ErrorSummary
          error={transition.error ?? assign.error ?? addComment.error}
        />
      )}
      {assignOpen && (
        <section aria-label="Assign ticket" className="assign-panel panel">
          <h2>Assign ticket</h2>
          <form
            onSubmit={(event) => {
              event.preventDefault();
              assign.mutate();
            }}
          >
            <div className="form-field">
              <label htmlFor="assign-group">Support group</label>
              <select
                id="assign-group"
                onChange={(event) => {
                  setAssignGroup(event.target.value);
                }}
                required
                value={assignGroup}
              >
                <option value="">Select a group…</option>
                {supportGroups.map((groupId) => (
                  <option key={groupId} value={groupId}>
                    {data.assignment_group_id === groupId &&
                    data.assignment_group_name
                      ? data.assignment_group_name
                      : `Group ${groupId.slice(0, 8)}`}
                  </option>
                ))}
              </select>
            </div>
            <div className="checkbox-option">
              <input
                checked={assignToMe}
                id="assign-me"
                onChange={(event) => {
                  setAssignToMe(event.target.checked);
                }}
                type="checkbox"
              />
              <label htmlFor="assign-me">Assign to me</label>
            </div>
            <div className="form-field">
              <label htmlFor="assign-reason">Reason</label>
              <input
                id="assign-reason"
                maxLength={64}
                minLength={3}
                onChange={(event) => {
                  setAssignReason(event.target.value);
                }}
                required
                value={assignReason}
              />
            </div>
            <Button disabled={assign.isPending} type="submit">
              {assign.isPending ? "Assigning…" : "Confirm assignment"}
            </Button>
            <Button
              onClick={() => {
                setAssignOpen(false);
              }}
              variant="secondary"
            >
              Cancel
            </Button>
          </form>
        </section>
      )}
      <Tabs
        activeId={tab}
        items={DETAIL_TABS.map((item) => ({ id: item.id, label: item.label }))}
        label="Ticket sections"
        onChange={(id) => {
          setSearchParams(id === "overview" ? {} : { tab: id }, {
            replace: true,
          });
        }}
      />
      <div className="ticket-workspace">
        <div className="ticket-workspace__main">
          {tab === "overview" && (
            <Panel title="Details">
              <p className="ticket-description">
                {data.description ?? "No description provided."}
              </p>
              <MetadataGrid
                items={[
                  { label: "Project", value: data.project_name },
                  { label: "Request type", value: data.request_type_name },
                  { label: "Work type", value: data.work_type },
                  { label: "Service", value: data.service_name ?? "—" },
                  { label: "Environment", value: data.environment_name ?? "—" },
                  { label: "Reporter", value: data.reporter_name },
                  {
                    label: "Requested for",
                    value: data.requested_for_name ?? "—",
                  },
                  {
                    label: "Created",
                    value: new Date(data.created_at).toLocaleString(),
                  },
                  {
                    label: "Updated",
                    value: new Date(data.updated_at).toLocaleString(),
                  },
                ]}
              />
              {statusHistory.length > 0 && (
                <>
                  <h3>Recent status changes</h3>
                  <ol className="status-history">
                    {statusHistory.map((item) => (
                      <li key={item.id}>
                        <span>{item.actor_name ?? "System"}</span>
                        <time dateTime={item.created_at}>
                          {new Date(item.created_at).toLocaleString()}
                        </time>
                      </li>
                    ))}
                  </ol>
                </>
              )}
            </Panel>
          )}
          {tab === "activity" && (
            <section aria-labelledby="activity-heading" className="activity">
              <h2 id="activity-heading">Activity timeline</h2>
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
                        <span
                          className={`visibility ${item.classification.toLowerCase()}`}
                        >
                          {item.classification}
                        </span>
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
                  <label htmlFor="analyst-comment">Add an update</label>
                  <p id="analyst-comment-help">
                    {visibility === "PUBLIC"
                      ? "This comment is visible to the employee and support analysts."
                      : "This internal note is visible only to authorized analysts."}
                  </p>
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
                  <textarea
                    aria-describedby="analyst-comment-help"
                    id="analyst-comment"
                    onChange={(event) => {
                      setComment(event.target.value);
                    }}
                    required
                    rows={4}
                    value={comment}
                  />
                </div>
                <Button disabled={addComment.isPending} type="submit">
                  {addComment.isPending
                    ? "Posting…"
                    : visibility === "INTERNAL"
                      ? "Post internal note"
                      : "Post public comment"}
                </Button>
              </form>
            </section>
          )}
          {tab === "attachments" && (
            <Panel>
              {attachments.isPending && (
                <StatusPanel>Loading attachments…</StatusPanel>
              )}
              {attachments.error && <ErrorSummary error={attachments.error} />}
              {download.error && <ErrorSummary error={download.error} />}
              {attachments.data && (
                <AttachmentList
                  items={attachments.data.items}
                  onDownload={(id) => {
                    download.mutate(id);
                  }}
                />
              )}
              <AttachmentUploader
                analyst
                client={client}
                ticketKey={ticketKey}
              />
            </Panel>
          )}
          {tab === "participants" && (
            <Panel title="Participants">
              <ul className="participant-list">
                {data.assignee_name && (
                  <li>
                    <ParticipantCard
                      name={data.assignee_name}
                      role="Assignee"
                    />
                  </li>
                )}
                <li>
                  <ParticipantCard name={data.reporter_name} role="Reporter" />
                </li>
                {data.requested_for_name && (
                  <li>
                    <ParticipantCard
                      name={data.requested_for_name}
                      role="Requested for"
                    />
                  </li>
                )}
              </ul>
              <EmptyState
                description="Adding and removing participants arrives with a future milestone."
                title="Participant management is not yet available"
              />
            </Panel>
          )}
          {tab === "worklog" && (
            <Panel title="Work Log">
              <EmptyState
                description="Work log tracking arrives with a future milestone."
                title="Not available yet"
              />
            </Panel>
          )}
        </div>
        <TicketSidePanel>
          <TicketMetadata
            items={[
              {
                label: "Status",
                value: <StatusBadge status={data.status_name} />,
              },
              {
                label: "Priority",
                value: <PriorityBadge priority={data.priority} />,
              },
              { label: "Impact", value: data.impact_code },
              { label: "Urgency", value: data.urgency_code },
              {
                label: "Assignment group",
                value: data.assignment_group_name ?? "Unassigned",
              },
              { label: "Assignee", value: data.assignee_name ?? "Unassigned" },
              ...slas.map((sla) => ({
                label: `SLA ${sla.definition_code}`,
                value: `${slaPresentation(sla).label} — ${slaPresentation(sla).detail}`,
              })),
              ...(slas.length === 0
                ? [{ label: "SLA", value: "No SLA applied" }]
                : []),
              { label: "Reporter", value: data.reporter_name },
              {
                label: "Created",
                value: new Date(data.created_at).toLocaleString(),
              },
              {
                label: "Updated",
                value: new Date(data.updated_at).toLocaleString(),
              },
            ]}
          />
        </TicketSidePanel>
      </div>
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
                  <Button disabled={addComment.isPending} type="submit">
                    {addComment.isPending
                      ? "Posting…"
                      : visibility === "INTERNAL"
                        ? "Post internal note"
                        : "Post public comment"}
                  </Button>
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

type KnowledgeArticlesQuery = NonNullable<
  paths["/api/v1/knowledge/articles"]["get"]["parameters"]["query"]
>;

function KnowledgeLandingPage({ analyst }: { analyst: boolean }) {
  const client = useIdentityClient();
  const basePath = analyst ? "/agent/knowledge" : "/portal/knowledge";
  const persona = analyst ? ("ANALYST" as const) : ("EMPLOYEE" as const);
  const [searchParams, setSearchParams] = useSearchParams();
  const query = searchParams.get("q") ?? "";
  const documentType = searchParams.get("type");
  const [searchInput, setSearchInput] = useState(query);
  useEffect(() => {
    setSearchInput(query);
  }, [query]);
  const articles = useQuery({
    queryKey: ["knowledge-articles", persona, documentType],
    enabled: query.length === 0,
    queryFn: async () =>
      unwrap(
        await client.GET("/api/v1/knowledge/articles", {
          params: {
            query: {
              persona,
              limit: 20,
              ...(documentType === null
                ? {}
                : {
                    document_type:
                      documentType as KnowledgeArticlesQuery["document_type"],
                  }),
            },
          },
        }),
      ),
  });
  const search = useQuery({
    queryKey: ["knowledge-search", persona, query],
    enabled: query.length > 0,
    queryFn: async () =>
      unwrap(
        await client.POST("/api/v1/knowledge/evidence/search", {
          body: { query, persona, limit: 20 },
        }),
      ),
  });
  const submitSearch = (event: SyntheticEvent) => {
    event.preventDefault();
    const trimmed = searchInput.trim();
    setSearchParams(trimmed ? { q: trimmed } : {});
  };
  const groups = search.data
    ? groupEvidenceByDocument(search.data.evidence)
    : [];
  return (
    <div className="page knowledge-page">
      <PageHeader
        description="Search approved articles or browse by type."
        title="Knowledge Base"
      />
      <form className="knowledge-search" onSubmit={submitSearch} role="search">
        <SearchField
          className="knowledge-search__field"
          label="Search knowledge articles"
          onChange={setSearchInput}
          placeholder="Search knowledge articles…"
          value={searchInput}
        />
        <Button type="submit">Search</Button>
      </form>
      {query.length > 0 && (
        <section aria-label="Search results">
          <SectionHeader
            action={
              <Button
                onClick={() => {
                  setSearchParams({});
                }}
                variant="secondary"
              >
                Clear search
              </Button>
            }
            title={`Results for “${query}”`}
          />
          {search.isPending && <LoadingSkeleton label="Searching articles" />}
          {search.error && <ErrorSummary error={search.error} />}
          {search.data && groups.length === 0 && (
            <EmptyState
              description="No articles match your search. Try different words or remove filters."
              title="No results"
            />
          )}
          {groups.length > 0 && (
            <ul className="search-result-list">
              {groups.map((group) => (
                <li className="search-result" key={group.top.document_id}>
                  <h3>
                    <Link
                      state={{ fromSearch: `?q=${encodeURIComponent(query)}` }}
                      to={`${basePath}/articles/${group.top.document_id}`}
                    >
                      {group.top.document_title}
                    </Link>
                  </h3>
                  <p className="search-result__type">
                    {group.top.document_type
                      ? documentTypeLabel(group.top.document_type)
                      : "Article"}
                    {group.top.section_title
                      ? ` · ${group.top.section_title}`
                      : ""}
                  </p>
                  <p className="search-result__excerpt">
                    {highlightMatches(group.top.content.slice(0, 300), query)}
                  </p>
                  {group.matchCount > 1 && (
                    <p className="search-result__count">
                      {group.matchCount} matching sections
                    </p>
                  )}
                </li>
              ))}
            </ul>
          )}
        </section>
      )}
      {query.length === 0 && (
        <>
          {articles.isPending && (
            <LoadingSkeleton label="Loading knowledge articles" />
          )}
          {articles.error && <ErrorSummary error={articles.error} />}
          {articles.data && (
            <>
              {articles.data.facets.length > 0 && (
                <section aria-label="Browse by type">
                  <SectionHeader
                    action={
                      documentType === null ? undefined : (
                        <Button
                          onClick={() => {
                            setSearchParams({});
                          }}
                          variant="secondary"
                        >
                          All types
                        </Button>
                      )
                    }
                    title="Browse by type"
                  />
                  <ul className="knowledge-facets">
                    {articles.data.facets.map((facet) => (
                      <li key={facet.document_type}>
                        <Link
                          aria-current={
                            documentType === facet.document_type
                              ? "true"
                              : undefined
                          }
                          className={`knowledge-facet${
                            documentType === facet.document_type
                              ? " knowledge-facet--active"
                              : ""
                          }`}
                          to={`${basePath}?type=${facet.document_type}`}
                        >
                          <strong>
                            {documentTypeLabel(facet.document_type)}
                          </strong>
                          <span>
                            {facet.count}{" "}
                            {facet.count === 1 ? "article" : "articles"}
                          </span>
                        </Link>
                      </li>
                    ))}
                  </ul>
                </section>
              )}
              <section aria-label="Articles">
                <SectionHeader
                  title={
                    documentType === null
                      ? "Recently updated"
                      : `${documentTypeLabel(documentType)} articles`
                  }
                />
                {articles.data.items.length === 0 && (
                  <EmptyState description="No published articles yet." />
                )}
                {articles.data.items.length > 0 && (
                  <div className="article-grid">
                    {articles.data.items.map((item) => (
                      <ArticleCard
                        documentType={item.document_type}
                        excerpt={item.excerpt}
                        href={`${basePath}/articles/${item.id}`}
                        key={item.id}
                        meta={`${item.source_name} · Updated ${new Date(item.updated_at).toLocaleDateString()}`}
                        title={item.title}
                      />
                    ))}
                  </div>
                )}
                {articles.data.has_more && (
                  <p className="knowledge-more">
                    Showing the 20 most recently updated articles. Refine by
                    type or search to narrow results.
                  </p>
                )}
              </section>
            </>
          )}
        </>
      )}
    </div>
  );
}

function KnowledgeArticlePage({ analyst }: { analyst: boolean }) {
  const client = useIdentityClient();
  const { documentId = "" } = useParams();
  const location = useLocation();
  const basePath = analyst ? "/agent/knowledge" : "/portal/knowledge";
  const persona = analyst ? ("ANALYST" as const) : ("EMPLOYEE" as const);
  const [copied, setCopied] = useState(false);
  const article = useQuery({
    queryKey: ["knowledge-article", persona, documentId],
    queryFn: async () =>
      unwrap(
        await client.GET("/api/v1/knowledge/articles/{document_id}", {
          params: { path: { document_id: documentId }, query: { persona } },
        }),
      ),
  });
  const fromSearch =
    (location.state as { fromSearch?: string } | null)?.fromSearch ?? "";
  if (article.isPending) {
    return (
      <div className="page">
        <LoadingSkeleton label="Loading article" lines={6} />
      </div>
    );
  }
  if (article.error) {
    const notFound =
      article.error instanceof ApiProblem && article.error.status === 404;
    return (
      <div className="page">
        <Breadcrumbs
          items={[
            { label: "Knowledge Base", to: `${basePath}${fromSearch}` },
            { label: "Article" },
          ]}
        />
        {notFound ? (
          <EmptyState
            description="It may have been retired, or you may not have access to it."
            title="Article unavailable"
          />
        ) : (
          <ErrorSummary error={article.error} />
        )}
      </div>
    );
  }
  const data = article.data;
  const sections = data.sections ?? [];
  const copyLink = () => {
    void navigator.clipboard.writeText(window.location.href).then(() => {
      setCopied(true);
    });
  };
  const metadata: { label: string; value: ReactNode }[] = [
    { label: "Type", value: documentTypeLabel(data.document_type) },
    { label: "Source", value: data.source_name },
  ];
  if (data.product_name)
    metadata.push({ label: "Product", value: data.product_name });
  if (data.release_code)
    metadata.push({ label: "Release", value: data.release_code });
  metadata.push({ label: "Language", value: data.language_code });
  metadata.push({ label: "Version", value: String(data.version_number) });
  if (data.published_at)
    metadata.push({
      label: "Published",
      value: new Date(data.published_at).toLocaleString(),
    });
  metadata.push({
    label: "Updated",
    value: new Date(data.updated_at).toLocaleString(),
  });
  if (analyst) {
    metadata.push({ label: "Audience", value: data.audience_code });
    metadata.push({
      label: "Classification",
      value: data.security_classification,
    });
  }
  if (data.owner_group_name)
    metadata.push({ label: "Owner group", value: data.owner_group_name });
  if (data.policy_owner)
    metadata.push({ label: "Policy owner", value: data.policy_owner });
  if (data.process_owner)
    metadata.push({ label: "Process owner", value: data.process_owner });
  return (
    <div className="page article-page">
      <Breadcrumbs
        items={[
          { label: "Knowledge Base", to: `${basePath}${fromSearch}` },
          { label: data.title },
        ]}
      />
      <PageHeader
        actions={
          <>
            {copied && <span role="status">Link copied</span>}
            <Button onClick={copyLink} variant="secondary">
              Copy link
            </Button>
          </>
        }
        eyebrow={documentTypeLabel(data.document_type)}
        title={data.title}
      />
      <div className="article-layout">
        <div className="article-body">
          {sections.length === 0 && (
            <EmptyState
              description="This article has no readable content in your workspace."
              title="Content unavailable"
            />
          )}
          {sections.map((section, index) => (
            <section
              className="article-section"
              id={section.section_anchor ?? undefined}
              key={section.section_anchor ?? `section-${String(index)}`}
            >
              {(section.section_title ?? section.heading_path) && (
                <h2>{section.section_title ?? section.heading_path}</h2>
              )}
              <p className="article-section__content">{section.content}</p>
            </section>
          ))}
        </div>
        <TicketSidePanel title="Article information">
          <MetadataGrid items={metadata} />
          {data.canonical_url && (
            <p className="article-source">
              <a
                href={data.canonical_url}
                rel="noopener noreferrer"
                target="_blank"
              >
                View original source
              </a>
            </p>
          )}
        </TicketSidePanel>
      </div>
    </div>
  );
}

function AdminLandingPage() {
  const client = useIdentityClient();
  const overview = useQuery({
    queryKey: ["admin-overview"],
    queryFn: async () => unwrap(await client.GET("/api/v1/admin/overview")),
  });
  return (
    <div className="page admin-page">
      <PageHeader
        description="Tenant activity at a glance, with audit history and system status."
        title="Administration"
      />
      {overview.isPending && <LoadingSkeleton label="Loading overview" />}
      {overview.error && <ErrorSummary error={overview.error} />}
      {overview.data && (
        <div className="admin-stats">
          <StatCard label="Active users" value={overview.data.active_users} />
          <StatCard
            label="Support groups"
            value={overview.data.support_groups}
          />
          <StatCard label="Open tickets" value={overview.data.open_tickets} />
          <StatCard
            label="Knowledge articles"
            value={overview.data.published_knowledge_documents}
          />
        </div>
      )}
      <SectionHeader title="Administration areas" />
      <div className="admin-cards">
        <article className="admin-card">
          <h3>
            <Link to="/admin/audit">Audit logs</Link>
          </h3>
          <p>
            Review recorded activity and security decisions for this tenant.
          </p>
        </article>
        <article className="admin-card">
          <h3>
            <Link to="/admin/system">System status</Link>
          </h3>
          <p>Application version, migration head, and dependency health.</p>
        </article>
      </div>
      <p className="admin-note">
        User, role, queue, workflow, SLA, and catalogue management arrive with
        later milestones.
      </p>
    </div>
  );
}

const AUDIT_VIEWS = [
  { id: "activity", label: "Activity" },
  { id: "security", label: "Security" },
] as const;

function AdminAuditPage() {
  const client = useIdentityClient();
  const [searchParams, setSearchParams] = useSearchParams();
  const view =
    searchParams.get("view") === "security" ? "security" : "activity";
  const [page, setPage] = useState(0);
  const [outcome, setOutcome] = useState("");
  const [decision, setDecision] = useState("");
  const limit = 25;
  const activity = useQuery({
    queryKey: ["admin-audit-events", page, outcome],
    enabled: view === "activity",
    queryFn: async () =>
      unwrap(
        await client.GET("/api/v1/admin/audit/events", {
          params: {
            query: {
              limit,
              offset: page * limit,
              ...(outcome === ""
                ? {}
                : {
                    outcome_code: outcome as
                      "DENIED" | "FAILED" | "PARTIAL" | "SUCCESS",
                  }),
            },
          },
        }),
      ),
  });
  const security = useQuery({
    queryKey: ["admin-security-events", page, decision],
    enabled: view === "security",
    queryFn: async () =>
      unwrap(
        await client.GET("/api/v1/admin/audit/security-events", {
          params: {
            query: {
              limit,
              offset: page * limit,
              ...(decision === ""
                ? {}
                : { decision_code: decision as "ALLOWED" | "DENIED" }),
            },
          },
        }),
      ),
  });
  const active = view === "activity" ? activity : security;
  const hasMore =
    view === "activity"
      ? (activity.data?.has_more ?? false)
      : (security.data?.has_more ?? false);
  return (
    <div className="page admin-page">
      <PageHeader
        description="Read-only, tenant-scoped audit history. Events are append-only."
        title="Audit logs"
      />
      <Tabs
        activeId={view}
        items={AUDIT_VIEWS}
        label="Audit event views"
        onChange={(id) => {
          setPage(0);
          setSearchParams(id === "activity" ? {} : { view: id });
        }}
      />
      <div className="admin-filter">
        {view === "activity" ? (
          <label>
            Outcome
            <select
              onChange={(event) => {
                setPage(0);
                setOutcome(event.target.value);
              }}
              value={outcome}
            >
              <option value="">All outcomes</option>
              <option value="SUCCESS">Success</option>
              <option value="DENIED">Denied</option>
              <option value="FAILED">Failed</option>
              <option value="PARTIAL">Partial</option>
            </select>
          </label>
        ) : (
          <label>
            Decision
            <select
              onChange={(event) => {
                setPage(0);
                setDecision(event.target.value);
              }}
              value={decision}
            >
              <option value="">All decisions</option>
              <option value="ALLOWED">Allowed</option>
              <option value="DENIED">Denied</option>
            </select>
          </label>
        )}
      </div>
      {active.isPending && <LoadingSkeleton label="Loading audit events" />}
      {active.error && <ErrorSummary error={active.error} />}
      {view === "activity" && activity.data && (
        <>
          {activity.data.items.length === 0 && (
            <EmptyState description="No audit events match the current filters." />
          )}
          {activity.data.items.length > 0 && (
            <ul className="audit-list">
              {activity.data.items.map((item) => (
                <li className="audit-row" key={item.id}>
                  <div className="audit-row__main">
                    <strong>{humanizeCode(item.action_code)}</strong>
                    <span>
                      {humanizeCode(item.resource_type)}
                      {item.resource_id ? ` · ${item.resource_id}` : ""}
                    </span>
                  </div>
                  <div className="audit-row__meta">
                    <OutcomeBadge code={item.outcome_code} />
                    <span>{item.actor_type}</span>
                    <time dateTime={item.occurred_at}>
                      {new Date(item.occurred_at).toLocaleString()}
                    </time>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
      {view === "security" && security.data && (
        <>
          {security.data.items.length === 0 && (
            <EmptyState description="No security events match the current filters." />
          )}
          {security.data.items.length > 0 && (
            <ul className="audit-list">
              {security.data.items.map((item) => (
                <li className="audit-row" key={item.id}>
                  <div className="audit-row__main">
                    <strong>{humanizeCode(item.event_type)}</strong>
                    <span>
                      {item.resource_type
                        ? `${humanizeCode(item.resource_type)}${
                            item.resource_id ? ` · ${item.resource_id}` : ""
                          }`
                        : "—"}
                    </span>
                  </div>
                  <div className="audit-row__meta">
                    <OutcomeBadge code={item.decision_code} />
                    <time dateTime={item.occurred_at}>
                      {new Date(item.occurred_at).toLocaleString()}
                    </time>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
      {(page > 0 || hasMore) && (
        <Pagination
          hasNext={hasMore}
          onNext={() => {
            setPage((value) => value + 1);
          }}
          onPrevious={() => {
            setPage((value) => Math.max(0, value - 1));
          }}
          page={page + 1}
        />
      )}
    </div>
  );
}

function AdminSystemPage() {
  const client = useIdentityClient();
  const status = useQuery({
    queryKey: ["admin-system-status"],
    queryFn: async () =>
      unwrap(await client.GET("/api/v1/admin/system-status")),
  });
  const flag = (value: boolean) => (value ? "Enabled" : "Disabled");
  return (
    <div className="page admin-page">
      <PageHeader
        description="Safe configuration metadata and dependency health. No secrets are shown."
        title="System status"
      />
      {status.isPending && <LoadingSkeleton label="Loading system status" />}
      {status.error && <ErrorSummary error={status.error} />}
      {status.data && (
        <div className="admin-status">
          <Panel title="Application">
            <MetadataGrid
              items={[
                { label: "Version", value: status.data.app_version },
                { label: "Environment", value: status.data.environment },
                {
                  label: "Migration head",
                  value: status.data.migration_head ?? "Unknown",
                },
                {
                  label: "Embedding provider",
                  value: status.data.retrieval_embedding_provider,
                },
              ]}
            />
          </Panel>
          <Panel title="Feature flags">
            <MetadataGrid
              items={[
                {
                  label: "OIDC sign-in",
                  value: flag(status.data.oidc_enabled),
                },
                {
                  label: "Developer identity",
                  value: flag(status.data.developer_identity_enabled),
                },
                {
                  label: "AI assistance",
                  value: flag(status.data.ai_globally_enabled),
                },
                {
                  label: "Object storage",
                  value: flag(status.data.object_storage_enabled),
                },
                {
                  label: "Malware scanning required",
                  value: flag(status.data.clamav_required),
                },
                {
                  label: "Metrics endpoint",
                  value: flag(status.data.metrics_endpoint_enabled),
                },
                {
                  label: "Row-level security",
                  value: flag(status.data.rls_enabled),
                },
              ]}
            />
          </Panel>
          <Panel title="Dependencies">
            <ul className="dependency-list">
              {status.data.dependencies.map((dependency) => (
                <li key={dependency.name}>
                  {dependency.status === "disabled" ? (
                    <span className="dependency-disabled">
                      {humanizeCode(dependency.name.toUpperCase())} — disabled
                    </span>
                  ) : (
                    <HealthIndicator
                      healthy={dependency.status === "healthy"}
                      label={humanizeCode(dependency.name.toUpperCase())}
                    />
                  )}
                  {!dependency.required && (
                    <span className="dependency-optional">Optional</span>
                  )}
                </li>
              ))}
            </ul>
          </Panel>
        </div>
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
          path="/portal/knowledge"
          element={
            <RequireSession>
              <RequirePermission permission="KNOWLEDGE_READ_EMPLOYEE">
                <KnowledgeLandingPage analyst={false} />
              </RequirePermission>
            </RequireSession>
          }
        />
        <Route
          path="/portal/knowledge/articles/:documentId"
          element={
            <RequireSession>
              <RequirePermission permission="KNOWLEDGE_READ_EMPLOYEE">
                <KnowledgeArticlePage analyst={false} />
              </RequirePermission>
            </RequireSession>
          }
        />
        <Route
          path="/agent/knowledge"
          element={
            <RequireSession>
              <RequirePermission permission="KNOWLEDGE_READ_ANALYST">
                <KnowledgeLandingPage analyst />
              </RequirePermission>
            </RequireSession>
          }
        />
        <Route
          path="/agent/knowledge/articles/:documentId"
          element={
            <RequireSession>
              <RequirePermission permission="KNOWLEDGE_READ_ANALYST">
                <KnowledgeArticlePage analyst />
              </RequirePermission>
            </RequireSession>
          }
        />
        <Route
          path="/agent/dashboard"
          element={
            <RequireSession>
              <RequirePermission permission="TICKET_ANALYST_READ">
                <AnalystDashboardPage />
              </RequirePermission>
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
                <AnalystTicketDetailPage />
              </RequirePermission>
            </RequireSession>
          }
        />
        <Route
          path="/admin"
          element={
            <RequireSession>
              <RequirePermission permission="ADMIN_IDENTITY_READ">
                <AdminLandingPage />
              </RequirePermission>
            </RequireSession>
          }
        />
        <Route
          path="/admin/audit"
          element={
            <RequireSession>
              <RequirePermission permission="AUDIT_EVENT_READ">
                <AdminAuditPage />
              </RequirePermission>
            </RequireSession>
          }
        />
        <Route
          path="/admin/system"
          element={
            <RequireSession>
              <RequirePermission permission="SYSTEM_HEALTH_READ">
                <AdminSystemPage />
              </RequirePermission>
            </RequireSession>
          }
        />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </AppShell>
  );
}
