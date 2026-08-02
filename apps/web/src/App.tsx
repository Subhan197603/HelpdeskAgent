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
  useNavigate,
  useParams,
} from "react-router-dom";

import { ErrorSummary, StatusPanel } from "./components/StatusPanel";
import { apiClient, newIdempotencyKey, unwrap } from "./lib/api";
import { type Persona, useSession } from "./lib/session";

type FormField = components["schemas"]["FormFieldResponse"];
type RequestForm = components["schemas"]["RequestFormResponse"];
type Draft = components["schemas"]["DraftResponse"];
type FieldValue = string | string[] | boolean;

function RequireSession({ children }: { children: ReactNode }) {
  const { session } = useSession();
  return session ? children : <Navigate to="/login" replace />;
}

function Shell({ children }: { children: ReactNode }) {
  const { session, signOut } = useSession();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  return (
    <div className="app-shell">
      <header className="topbar">
        <Link
          className="brand"
          to={session?.persona === "analyst" ? "/agent/tickets" : "/portal"}
        >
          <span aria-hidden="true" className="brand-mark">
            F
          </span>
          <span>Fusion Helpdesk</span>
        </Link>
        {session && (
          <nav aria-label="Primary navigation">
            {session.persona === "employee" ? (
              <>
                <Link to="/portal/catalog">Catalogue</Link>
                <Link to="/portal/requests">My requests</Link>
              </>
            ) : (
              <Link to="/agent/tickets">Analyst queues</Link>
            )}
            <button
              className="button-link"
              onClick={() => {
                queryClient.clear();
                signOut();
                navigate("/login");
              }}
              type="button"
            >
              Sign out
            </button>
          </nav>
        )}
      </header>
      <main id="main-content">{children}</main>
    </div>
  );
}

export function LoginPage() {
  const { session, signIn } = useSession();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  if (session) {
    return (
      <Navigate
        to={session.persona === "analyst" ? "/agent/tickets" : "/portal"}
      />
    );
  }
  const enter = (persona: Persona) => {
    queryClient.clear();
    signIn({
      persona,
      identity: persona === "analyst" ? "DEV/agent" : "DEV/customer",
    });
    navigate(persona === "analyst" ? "/agent/tickets" : "/portal");
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
        <div className="login-actions">
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
        </div>
        <p className="development-note">Development identity mode</p>
      </section>
    </div>
  );
}

function PortalHome() {
  return (
    <div className="page hero-page">
      <p className="eyebrow">Employee portal</p>
      <h1>Get the right help, without the runaround.</h1>
      <p className="lede">
        Choose a configured service request and track every public update.
      </p>
      <div className="hero-actions">
        <Link className="button primary" to="/portal/catalog">
          Browse the service catalogue
        </Link>
        <Link className="button secondary" to="/portal/requests">
          View my requests
        </Link>
      </div>
    </div>
  );
}

function useIdentityClient() {
  const { session } = useSession();
  return useMemo(() => apiClient(session?.identity ?? ""), [session?.identity]);
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
    <div className="page narrow-page">
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
      <p className="eyebrow">
        {analyst ? "Analyst workspace" : "Employee portal"}
      </p>
      <h1>{analyst ? "Tickets needing attention" : "My requests"}</h1>
      {tickets.isPending && <StatusPanel>Loading tickets…</StatusPanel>}
      {tickets.error && <ErrorSummary error={tickets.error} />}
      {tickets.data?.items.length === 0 && (
        <StatusPanel>
          {analyst
            ? "No accessible tickets are waiting."
            : "You have no requests yet."}
        </StatusPanel>
      )}
      <div className="ticket-list">
        {tickets.data?.items.map((ticket) => (
          <Link
            className="ticket-row"
            key={ticket.id}
            to={
              analyst
                ? `/agent/tickets/${ticket.key}`
                : `/portal/requests/${ticket.key}`
            }
          >
            <span className="ticket-key">{ticket.key}</span>
            <span>
              <strong>{ticket.summary}</strong>
              <small>{ticket.request_type_name}</small>
            </span>
            <span className="pill">{ticket.status_name}</span>
            <span className="priority">{ticket.priority}</span>
          </Link>
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
      <p className="eyebrow">Analyst workspace</p>
      <h1>Ticket queues</h1>
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
                <Link
                  className="ticket-row"
                  key={ticket.id}
                  to={`/agent/tickets/${ticket.key}`}
                >
                  <span className="ticket-key">{ticket.key}</span>
                  <span>
                    <strong>{ticket.summary}</strong>
                    <small>
                      {ticket.assignment_group_name ?? "Unassigned"}
                      {ticket.assignee_name ? ` · ${ticket.assignee_name}` : ""}
                    </small>
                  </span>
                  <span className="pill">{ticket.status_name}</span>
                  <span className="priority">{ticket.priority}</span>
                </Link>
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
    <div className="page narrow-page">
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
          <div className="ticket-heading">
            <div>
              <p className="eyebrow">{ticket.data.key}</p>
              <h1>{ticket.data.summary}</h1>
            </div>
            <span className="pill">{ticket.data.status_name}</span>
          </div>
          <dl className="details">
            <div>
              <dt>Request type</dt>
              <dd>{ticket.data.request_type_name}</dd>
            </div>
            <div>
              <dt>Priority</dt>
              <dd>{ticket.data.priority}</dd>
            </div>
            <div>
              <dt>Reporter</dt>
              <dd>{ticket.data.reporter_name}</dd>
            </div>
            <div>
              <dt>Created</dt>
              <dd>{new Date(ticket.data.created_at).toLocaleString()}</dd>
            </div>
          </dl>
          <section aria-labelledby="activity-heading" className="activity">
            <h2 id="activity-heading">
              {analyst ? "Activity timeline" : "Public activity"}
            </h2>
            {timeline.isPending && <StatusPanel>Loading activity…</StatusPanel>}
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
        </>
      )}
    </div>
  );
}

export function App() {
  return (
    <Shell>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/" element={<Navigate to="/portal" replace />} />
        <Route
          path="/portal"
          element={
            <RequireSession>
              <PortalHome />
            </RequireSession>
          }
        />
        <Route
          path="/portal/catalog"
          element={
            <RequireSession>
              <CataloguePage />
            </RequireSession>
          }
        />
        <Route
          path="/portal/catalog/:requestTypeId"
          element={
            <RequireSession>
              <RequestFormPage />
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
              <AgentQueuePage />
            </RequireSession>
          }
        />
        <Route
          path="/agent/tickets/:ticketKey"
          element={
            <RequireSession>
              <TicketDetailPage analyst />
            </RequireSession>
          }
        />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Shell>
  );
}
