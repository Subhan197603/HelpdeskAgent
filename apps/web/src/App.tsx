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

import {
  ActiveBadge,
  aiSafetyPresentation,
  CodeChips,
  formatEstimatedCost,
  formatMinutes,
  formatTokenCount,
  humanizeCode,
  isoDayName,
  OutcomeBadge,
} from "./components/Admin";
import {
  AppShell,
  RequirePermission,
  useCurrentIdentity,
} from "./components/AppShell";
import { DataTable, Pagination, TableToolbar } from "./components/DataTable";
import { AttachmentUploader } from "./components/AttachmentUploader";
import {
  HealthIndicator,
  PriorityBadge,
  SlaBadge,
  StatusBadge,
} from "./components/Badges";
import { Button } from "./components/Button";
import { ActivityFeed, DonutChart, formatDelta } from "./components/Dashboard";
import { ConfirmationDialog, TextArea } from "./components/Forms";
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
type SavedFilter = components["schemas"]["SavedFilterResponse"];
type CannedResponse = components["schemas"]["CannedResponseResponse"];
type FieldValue = string | string[] | boolean;
type AIPolicy = components["schemas"]["AIPolicySummaryResponse"];

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

export function insertCannedResponse(draft: string, snippet: string) {
  if (!draft) return snippet;
  return `${draft.trimEnd()}\n\n${snippet}`;
}

export function watchActionLabel(watched: boolean, pending: boolean) {
  if (pending) return watched ? "Unwatching…" : "Watching…";
  return watched ? "Unwatch" : "Watch";
}

function CannedResponseTools({
  draft,
  onDraftChange,
}: {
  draft: string;
  onDraftChange: (value: string) => void;
}) {
  const client = useIdentityClient();
  const queryClient = useQueryClient();
  const queryKey = ["agent-canned-responses"];
  const [selectedId, setSelectedId] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [body, setBody] = useState("");
  const cannedResponses = useQuery({
    queryKey,
    queryFn: async () =>
      unwrap(await client.GET("/api/v1/agent/canned-responses")),
  });
  const selected = cannedResponses.data?.items.find(
    (item) => item.id === selectedId,
  );
  const resetForm = () => {
    setEditingId(null);
    setName("");
    setBody("");
  };
  const create = useMutation({
    mutationFn: async () =>
      unwrap(
        await client.POST("/api/v1/agent/canned-responses", {
          params: {
            header: {
              "Idempotency-Key": newIdempotencyKey("canned-response"),
            },
          },
          body: { name, body },
        }),
      ),
    onSuccess: (item) => {
      resetForm();
      setSelectedId(item.id);
      void queryClient.invalidateQueries({ queryKey });
    },
  });
  const update = useMutation({
    mutationFn: async (item: CannedResponse) =>
      unwrap(
        await client.PATCH(
          "/api/v1/agent/canned-responses/{canned_response_id}",
          {
            params: {
              path: { canned_response_id: item.id },
              header: { "If-Match": String(item.row_version) },
            },
            body: { name, body, row_version: item.row_version },
          },
        ),
      ),
    onSuccess: () => {
      resetForm();
      void queryClient.invalidateQueries({ queryKey });
    },
  });
  const remove = useMutation({
    mutationFn: async (item: CannedResponse) => {
      const result = await client.DELETE(
        "/api/v1/agent/canned-responses/{canned_response_id}",
        {
          params: {
            path: { canned_response_id: item.id },
            header: { "If-Match": String(item.row_version) },
          },
          body: { row_version: item.row_version },
        },
      );
      if (!result.response.ok) unwrap(result);
    },
    onSuccess: () => {
      resetForm();
      setSelectedId("");
      void queryClient.invalidateQueries({ queryKey });
    },
  });
  const reorder = useMutation({
    mutationFn: async (items: CannedResponse[]) =>
      unwrap(
        await client.PUT("/api/v1/agent/canned-responses/order", {
          body: {
            items: items.map((item) => ({
              id: item.id,
              row_version: item.row_version,
            })),
          },
        }),
      ),
    onSuccess: (data) => {
      queryClient.setQueryData(queryKey, data);
    },
  });
  const move = (offset: number) => {
    const items = [...(cannedResponses.data?.items ?? [])];
    const index = items.findIndex((item) => item.id === selectedId);
    const target = index + offset;
    if (index < 0 || target < 0 || target >= items.length) return;
    const current = items[index];
    const destination = items[target];
    if (!current || !destination) return;
    items[index] = destination;
    items[target] = current;
    reorder.mutate(items);
  };
  const error = create.error ?? update.error ?? remove.error ?? reorder.error;
  return (
    <section
      aria-labelledby="canned-responses-heading"
      className="canned-responses"
    >
      <h3 id="canned-responses-heading">Personal canned responses</h3>
      <p id="canned-response-help">
        Insert editable text into this draft. Visibility and posting stay
        unchanged.
      </p>
      {cannedResponses.isPending && (
        <StatusPanel>Loading canned responses…</StatusPanel>
      )}
      {cannedResponses.error && <ErrorSummary error={cannedResponses.error} />}
      {error && <ErrorSummary error={error} />}
      {cannedResponses.data?.items.length === 0 && (
        <StatusPanel>No canned responses yet.</StatusPanel>
      )}
      <label htmlFor="canned-response-select">Choose a canned response</label>
      <select
        aria-describedby="canned-response-help"
        id="canned-response-select"
        onChange={(event) => {
          setSelectedId(event.target.value);
        }}
        value={selectedId}
      >
        <option value="">Select a response…</option>
        {cannedResponses.data?.items.map((item) => (
          <option key={item.id} value={item.id}>
            {item.name}
          </option>
        ))}
      </select>
      <div className="canned-response-actions">
        <Button
          disabled={!selected}
          onClick={() => {
            if (selected)
              onDraftChange(insertCannedResponse(draft, selected.body));
          }}
          type="button"
        >
          Insert response
        </Button>
        <Button
          disabled={!selected}
          onClick={() => {
            if (!selected) return;
            setEditingId(selected.id);
            setName(selected.name);
            setBody(selected.body);
          }}
          type="button"
          variant="secondary"
        >
          Edit
        </Button>
        <Button
          disabled={!selected}
          onClick={() => {
            move(-1);
          }}
          type="button"
          variant="secondary"
        >
          Move up
        </Button>
        <Button
          disabled={!selected}
          onClick={() => {
            move(1);
          }}
          type="button"
          variant="secondary"
        >
          Move down
        </Button>
        <Button
          disabled={!selected || remove.isPending}
          onClick={() => {
            if (selected) remove.mutate(selected);
          }}
          type="button"
          variant="secondary"
        >
          Delete
        </Button>
      </div>
      <div className="canned-response-form">
        <label htmlFor="canned-response-name">Response name</label>
        <input
          id="canned-response-name"
          maxLength={100}
          onChange={(event) => {
            setName(event.target.value);
          }}
          value={name}
        />
        <label htmlFor="canned-response-body">Response text</label>
        <textarea
          id="canned-response-body"
          maxLength={10000}
          onChange={(event) => {
            setBody(event.target.value);
          }}
          rows={4}
          value={body}
        />
        <div className="canned-response-actions">
          <Button
            disabled={
              !name.trim() ||
              !body.trim() ||
              create.isPending ||
              update.isPending
            }
            onClick={() => {
              const editing = cannedResponses.data?.items.find(
                (item) => item.id === editingId,
              );
              if (editing) update.mutate(editing);
              else create.mutate();
            }}
            type="button"
          >
            {editingId ? "Update response" : "Create response"}
          </Button>
          {editingId && (
            <Button onClick={resetForm} type="button" variant="secondary">
              Cancel
            </Button>
          )}
        </div>
      </div>
    </section>
  );
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
  const identity = useCurrentIdentity();
  const queryClient = useQueryClient();
  const [params, setParams] = useSearchParams();
  const savedFilterId = params.get("savedFilter");
  const editingFilterId = params.get("editFilter");
  const queueId = params.get("queue");
  const watchlistView = params.get("view") === "watched";
  const search = params.get("q") ?? "";
  const status = params.get("status") ?? "";
  const priority = params.get("priority") ?? "";
  const group = params.get("group") ?? "";
  const assignee = params.get("assignee") ?? "";
  const [searchInput, setSearchInput] = useState(search);
  const [filterName, setFilterName] = useState("");
  const [deleting, setDeleting] = useState<SavedFilter | null>(null);
  const [cursor, setCursor] = useState<string | null>(null);
  const queues = useQuery({
    queryKey: ["agent-queues"],
    queryFn: async () => unwrap(await client.GET("/api/v1/agent/queues")),
  });
  const savedFilters = useQuery({
    queryKey: ["agent-saved-filters"],
    queryFn: async () =>
      unwrap(await client.GET("/api/v1/agent/saved-filters")),
  });
  useEffect(() => {
    if (!queueId && !savedFilterId && !watchlistView && queues.data?.items[0]) {
      setParams({ queue: queues.data.items[0].id }, { replace: true });
    }
  }, [queueId, queues.data, savedFilterId, setParams, watchlistView]);
  useEffect(() => {
    setSearchInput(search);
  }, [search]);
  const editingFilter = savedFilters.data?.items.find(
    (item) => item.id === editingFilterId,
  );
  useEffect(() => {
    setFilterName(editingFilter?.name ?? "");
  }, [editingFilter]);
  const updateManualParams = (changes: Record<string, string | null>) => {
    const next = new URLSearchParams(params);
    next.delete("savedFilter");
    next.delete("view");
    for (const [key, value] of Object.entries(changes)) {
      if (value) next.set(key, value);
      else next.delete(key);
    }
    setCursor(null);
    setParams(next);
  };
  const tickets = useQuery({
    queryKey: [
      "agent-queue-tickets",
      savedFilterId,
      queueId,
      cursor,
      search,
      status,
      priority,
      group,
      assignee,
    ],
    enabled: Boolean(savedFilterId ?? queueId),
    queryFn: async () => {
      if (savedFilterId)
        return unwrap(
          await client.GET(
            "/api/v1/agent/saved-filters/{saved_filter_id}/tickets",
            {
              params: {
                path: { saved_filter_id: savedFilterId },
                query: { cursor: cursor ?? undefined },
              },
            },
          ),
        );
      if (!queueId) throw new Error("Select an analyst queue.");
      return unwrap(
        await client.GET("/api/v1/agent/queues/{queue_id}/tickets", {
          params: {
            path: { queue_id: queueId },
            query: {
              cursor: cursor ?? undefined,
              search: search || undefined,
              status_code: status || undefined,
              priority_code: priority || undefined,
              assignment_group_id: group || undefined,
              assignee:
                assignee === "me" || assignee === "unassigned"
                  ? assignee
                  : undefined,
            },
          },
        }),
      );
    },
  });
  const watchedTickets = useQuery({
    enabled: watchlistView,
    queryKey: ["agent-watched-tickets", cursor],
    queryFn: async () =>
      unwrap(
        await client.GET("/api/v1/agent/watched-tickets", {
          params: { query: { cursor: cursor ?? undefined } },
        }),
      ),
  });
  const createFilter = useMutation({
    mutationFn: async () => {
      if (!queueId) throw new Error("Select an analyst queue.");
      return unwrap(
        await client.POST("/api/v1/agent/saved-filters", {
          params: {
            header: {
              "Idempotency-Key": newIdempotencyKey("saved-filter"),
            },
          },
          body: {
            name: filterName.trim(),
            queue_id: queueId,
            search: search || null,
            status_code: status || null,
            priority_code: priority || null,
            assignment_group_id: group || null,
            assignee:
              assignee === "me" || assignee === "unassigned" ? assignee : null,
          },
        }),
      );
    },
    onSuccess: (item) => {
      setFilterName("");
      setParams({ savedFilter: item.id });
      void queryClient.invalidateQueries({ queryKey: ["agent-saved-filters"] });
    },
  });
  const updateFilter = useMutation({
    mutationFn: async (item: SavedFilter) => {
      if (!queueId) throw new Error("Select an analyst queue.");
      return unwrap(
        await client.PATCH("/api/v1/agent/saved-filters/{saved_filter_id}", {
          params: {
            path: { saved_filter_id: item.id },
            header: { "If-Match": String(item.row_version) },
          },
          body: {
            name: filterName.trim(),
            queue_id: queueId,
            search: search || null,
            status_code: status || null,
            priority_code: priority || null,
            assignment_group_id: group || null,
            assignee:
              assignee === "me" || assignee === "unassigned" ? assignee : null,
            row_version: item.row_version,
          },
        }),
      );
    },
    onSuccess: (item) => {
      setParams({ savedFilter: item.id });
      void queryClient.invalidateQueries({ queryKey: ["agent-saved-filters"] });
    },
  });
  const deleteFilter = useMutation({
    mutationFn: async (item: SavedFilter) => {
      const result = await client.DELETE(
        "/api/v1/agent/saved-filters/{saved_filter_id}",
        {
          params: {
            path: { saved_filter_id: item.id },
            header: { "If-Match": String(item.row_version) },
          },
          body: { row_version: item.row_version },
        },
      );
      if (!result.response.ok) unwrap(result);
    },
    onSuccess: () => {
      setDeleting(null);
      setFilterName("");
      setParams(
        queues.data?.items[0] ? { queue: queues.data.items[0].id } : {},
      );
      void queryClient.invalidateQueries({ queryKey: ["agent-saved-filters"] });
    },
  });
  const reorderFilters = useMutation({
    mutationFn: async (items: SavedFilter[]) =>
      unwrap(
        await client.PUT("/api/v1/agent/saved-filters/order", {
          body: {
            items: items.map((item) => ({
              id: item.id,
              row_version: item.row_version,
            })),
          },
        }),
      ),
    onSuccess: (data) => {
      queryClient.setQueryData(["agent-saved-filters"], data);
    },
  });
  const selectedSaved = savedFilters.data?.items.find(
    (item) => item.id === savedFilterId,
  );
  const selected = queues.data?.items.find(
    (queue) => queue.id === (selectedSaved?.queue_id ?? queueId),
  );
  const editSavedFilter = (item: SavedFilter) => {
    const next = new URLSearchParams({
      queue: item.queue_id,
      editFilter: item.id,
    });
    if (item.search) next.set("q", item.search);
    if (item.status_code) next.set("status", item.status_code);
    if (item.priority_code) next.set("priority", item.priority_code);
    if (item.assignment_group_id) next.set("group", item.assignment_group_id);
    if (item.assignee) next.set("assignee", item.assignee);
    setParams(next);
  };
  const moveFilter = (item: SavedFilter, offset: number) => {
    const items = [...(savedFilters.data?.items ?? [])];
    const index = items.findIndex((candidate) => candidate.id === item.id);
    const target = index + offset;
    if (index < 0 || target < 0 || target >= items.length) return;
    const targetItem = items[target];
    if (!targetItem) return;
    items[index] = targetItem;
    items[target] = item;
    reorderFilters.mutate(items);
  };
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
            <button
              aria-current={watchlistView ? "page" : undefined}
              className={watchlistView ? "active" : ""}
              onClick={() => {
                setCursor(null);
                setParams({ view: "watched" });
              }}
              type="button"
            >
              <strong>Watched tickets</strong>
              <small>Personal</small>
            </button>
            {queues.data.items.map((queue) => (
              <button
                aria-current={
                  !watchlistView && queue.id === selected?.id
                    ? "page"
                    : undefined
                }
                className={
                  !watchlistView && queue.id === selected?.id ? "active" : ""
                }
                key={queue.id}
                onClick={() => {
                  updateManualParams({ queue: queue.id, editFilter: null });
                }}
                type="button"
              >
                <strong>{queue.name}</strong>
                <small>{queue.project_code}</small>
              </button>
            ))}
          </nav>
          <section aria-labelledby="queue-heading" className="queue-results">
            <h2 id="queue-heading">
              {watchlistView ? "Watched tickets" : selected?.name}
            </h2>
            {watchlistView ? (
              <p>
                Your private watchlist. Ticket access is checked whenever this
                list is loaded.
              </p>
            ) : (
              selected?.description && <p>{selected.description}</p>
            )}
            {!watchlistView && (
              <section
                aria-labelledby="saved-filters-heading"
                className="saved-filters"
              >
                <h3 id="saved-filters-heading">Personal saved filters</h3>
                {savedFilters.isPending && (
                  <p role="status">Loading saved filters…</p>
                )}
                {savedFilters.error && (
                  <ErrorSummary error={savedFilters.error} />
                )}
                <label htmlFor="saved-filter-select">
                  Apply a saved filter
                </label>
                <select
                  id="saved-filter-select"
                  onChange={(event) => {
                    const id = event.target.value;
                    setCursor(null);
                    if (id) setParams({ savedFilter: id });
                    else if (queues.data.items[0])
                      setParams({ queue: queues.data.items[0].id });
                  }}
                  value={savedFilterId ?? ""}
                >
                  <option value="">Manual filters</option>
                  {savedFilters.data?.items.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.name}
                    </option>
                  ))}
                </select>
                {selectedSaved && (
                  <div className="saved-filter-actions">
                    <Button
                      onClick={() => {
                        editSavedFilter(selectedSaved);
                      }}
                      variant="secondary"
                    >
                      Edit
                    </Button>
                    <Button
                      disabled={
                        savedFilters.data?.items[0]?.id === selectedSaved.id ||
                        reorderFilters.isPending
                      }
                      onClick={() => {
                        moveFilter(selectedSaved, -1);
                      }}
                      variant="secondary"
                    >
                      Move up
                    </Button>
                    <Button
                      disabled={
                        savedFilters.data?.items.at(-1)?.id ===
                          selectedSaved.id || reorderFilters.isPending
                      }
                      onClick={() => {
                        moveFilter(selectedSaved, 1);
                      }}
                      variant="secondary"
                    >
                      Move down
                    </Button>
                    <Button
                      onClick={() => {
                        setDeleting(selectedSaved);
                      }}
                      variant="danger"
                    >
                      Delete
                    </Button>
                  </div>
                )}
              </section>
            )}
            {!watchlistView && !savedFilterId && (
              <div className="queue-filter-grid">
                <label>
                  Status code
                  <input
                    maxLength={50}
                    onChange={(event) => {
                      updateManualParams({
                        status: event.target.value.toUpperCase(),
                      });
                    }}
                    pattern="[A-Z][A-Z0-9_]*"
                    value={status}
                  />
                </label>
                <label>
                  Priority code
                  <input
                    maxLength={20}
                    onChange={(event) => {
                      updateManualParams({
                        priority: event.target.value.toUpperCase(),
                      });
                    }}
                    pattern="[A-Z][A-Z0-9_]*"
                    value={priority}
                  />
                </label>
                <label>
                  Assignment group
                  <select
                    onChange={(event) => {
                      updateManualParams({ group: event.target.value });
                    }}
                    value={group}
                  >
                    <option value="">Any permitted group</option>
                    {identity?.support_group_ids.map((id) => (
                      <option key={id} value={id}>
                        Group {id.slice(0, 8)}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Assignee
                  <select
                    onChange={(event) => {
                      updateManualParams({ assignee: event.target.value });
                    }}
                    value={assignee}
                  >
                    <option value="">Anyone</option>
                    <option value="me">Assigned to me</option>
                    <option value="unassigned">Unassigned</option>
                  </select>
                </label>
              </div>
            )}
            {!watchlistView && !savedFilterId && (
              <form
                className="queue-search"
                onSubmit={(event) => {
                  event.preventDefault();
                  updateManualParams({ q: searchInput.trim() });
                }}
                role="search"
              >
                <label htmlFor="queue-search">
                  Search ticket key or summary
                </label>
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
            )}
            {!watchlistView && !savedFilterId && (
              <form
                className="save-filter-form"
                onSubmit={(event) => {
                  event.preventDefault();
                  if (editingFilter) updateFilter.mutate(editingFilter);
                  else createFilter.mutate();
                }}
              >
                <label htmlFor="saved-filter-name">
                  {editingFilter ? "Rename saved filter" : "Saved filter name"}
                </label>
                <input
                  id="saved-filter-name"
                  maxLength={100}
                  onChange={(event) => {
                    setFilterName(event.target.value);
                  }}
                  required
                  value={filterName}
                />
                <Button
                  disabled={
                    !filterName.trim() ||
                    createFilter.isPending ||
                    updateFilter.isPending
                  }
                  type="submit"
                >
                  {editingFilter
                    ? "Update saved filter"
                    : "Save current filter"}
                </Button>
              </form>
            )}
            {!watchlistView &&
              (createFilter.error ??
                updateFilter.error ??
                reorderFilters.error) && (
                <ErrorSummary
                  error={
                    createFilter.error ??
                    updateFilter.error ??
                    reorderFilters.error
                  }
                />
              )}
            {!watchlistView && tickets.isPending && (
              <StatusPanel>Loading queue tickets…</StatusPanel>
            )}
            {!watchlistView && tickets.error && (
              <ErrorSummary error={tickets.error} />
            )}
            {!watchlistView && tickets.data?.items.length === 0 && (
              <StatusPanel>No tickets match this queue.</StatusPanel>
            )}
            {watchlistView && watchedTickets.isPending && (
              <StatusPanel>Loading watched tickets…</StatusPanel>
            )}
            {watchlistView && watchedTickets.error && (
              <ErrorSummary error={watchedTickets.error} />
            )}
            {watchlistView && watchedTickets.data?.items.length === 0 && (
              <StatusPanel>No watched tickets yet.</StatusPanel>
            )}
            {!watchlistView && (
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
            )}
            {watchlistView && (
              <div className="ticket-list">
                {watchedTickets.data?.items.map((ticket) => (
                  <QueueRow
                    href={`/agent/tickets/${ticket.key}`}
                    key={ticket.id}
                    priority={ticket.priority}
                    status={ticket.status_name}
                    summary={ticket.summary}
                    ticketKey={ticket.key}
                    metadata={`Watched ${formatDateTime(ticket.watched_at)}`}
                  />
                ))}
              </div>
            )}
            {!watchlistView && tickets.data?.next_cursor && (
              <Button
                onClick={() => {
                  setCursor(tickets.data.next_cursor ?? null);
                }}
                variant="secondary"
              >
                Next page
              </Button>
            )}
            {watchlistView && watchedTickets.data?.next_cursor && (
              <Button
                onClick={() => {
                  setCursor(watchedTickets.data.next_cursor ?? null);
                }}
                variant="secondary"
              >
                Next page
              </Button>
            )}
          </section>
        </div>
      )}
      <ConfirmationDialog
        confirmLabel="Delete saved filter"
        confirmVariant="danger"
        onCancel={() => {
          setDeleting(null);
        }}
        onConfirm={() => {
          if (deleting) deleteFilter.mutate(deleting);
        }}
        open={deleting != null}
        pending={deleteFilter.isPending}
        title={`Delete ${deleting?.name ?? "saved filter"}?`}
      >
        <p>This removes only your personal filter. No tickets will change.</p>
      </ConfirmationDialog>
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

export function ticketClassificationDisplay(value: string | null): string {
  return value ?? "Not provided";
}

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
  const watch = useMutation({
    mutationFn: async () => {
      if (ticket.data?.watched) {
        const result = await client.DELETE(
          "/api/v1/agent/tickets/{ticket_key}/watch",
          { params: { path: { ticket_key: ticketKey } } },
        );
        if (!result.response.ok) unwrap(result);
        return;
      }
      unwrap(
        await client.PUT("/api/v1/agent/tickets/{ticket_key}/watch", {
          params: { path: { ticket_key: ticketKey } },
        }),
      );
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ticketQueryKey });
      void queryClient.invalidateQueries({
        queryKey: ["agent-watched-tickets"],
      });
    },
  });
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
            <Button
              aria-pressed={data.watched}
              disabled={watch.isPending}
              onClick={() => {
                watch.mutate();
              }}
              variant="secondary"
            >
              {watchActionLabel(data.watched, watch.isPending)}
            </Button>
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
      {(watch.error ??
        transition.error ??
        assign.error ??
        addComment.error) && (
        <ErrorSummary
          error={
            watch.error ?? transition.error ?? assign.error ?? addComment.error
          }
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
                  <CannedResponseTools
                    draft={comment}
                    onDraftChange={setComment}
                  />
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
              {
                label: "Impact",
                value: ticketClassificationDisplay(data.impact_code),
              },
              {
                label: "Urgency",
                value: ticketClassificationDisplay(data.urgency_code),
              },
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
                      <>
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
                        <CannedResponseTools
                          draft={comment}
                          onDraftChange={setComment}
                        />
                      </>
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
            <Link to="/admin/knowledge">Knowledge</Link>
          </h3>
          <p>
            Review governed articles, versions, visibility, and publication
            state.
          </p>
        </article>
        <article className="admin-card">
          <h3>
            <Link to="/admin/users">Users</Link>
          </h3>
          <p>
            Browse workspace accounts with their roles, queues, and sign-in
            identities.
          </p>
        </article>
        <article className="admin-card">
          <h3>
            <Link to="/admin/roles">Roles</Link>
          </h3>
          <p>Review role definitions, permissions, and current assignments.</p>
        </article>
        <article className="admin-card">
          <h3>
            <Link to="/admin/queues">Queues</Link>
          </h3>
          <p>Support groups with membership, routing, and ticket views.</p>
        </article>
        <article className="admin-card">
          <h3>
            <Link to="/admin/workflows">Workflows</Link>
          </h3>
          <p>
            Ticket workflows with their statuses, transitions, and versions.
          </p>
        </article>
        <article className="admin-card">
          <h3>
            <Link to="/admin/sla-policies">SLA policies</Link>
          </h3>
          <p>Service level definitions, goals, and live cycle activity.</p>
        </article>
        <article className="admin-card">
          <h3>
            <Link to="/admin/calendars">Calendars</Link>
          </h3>
          <p>Business calendars with working hours and holiday exceptions.</p>
        </article>
        <article className="admin-card">
          <h3>
            <Link to="/admin/catalogue">Catalogue</Link>
          </h3>
          <p>Request types with forms, workflow mappings, and visibility.</p>
        </article>
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
        Configuration screens are read-only; new workflow, SLA, and form
        versions are authored in a later milestone. Catalogue portal visibility
        can be changed here.
      </p>
    </div>
  );
}

function AISafetyBadge({ code }: { code: string }) {
  const presentation = aiSafetyPresentation(code);
  return (
    <span className={`outcome-badge outcome-badge--${presentation.tone}`}>
      {presentation.label}
    </span>
  );
}

function policyScope(policy: AIPolicy): string {
  return (
    policy.agent_code ??
    policy.use_case_code ??
    policy.environment_code ??
    (policy.tenant_specific ? "Current tenant" : "Platform")
  );
}

function AdminAIGovernancePage() {
  const client = useIdentityClient();
  const [selectedPolicyId, setSelectedPolicyId] = useState<string | null>(null);
  const overview = useQuery({
    queryKey: ["admin-ai-overview"],
    queryFn: async () => unwrap(await client.GET("/api/v1/admin/ai")),
  });
  const policies = useQuery({
    queryKey: ["admin-ai-policies"],
    queryFn: async () =>
      unwrap(
        await client.GET("/api/v1/admin/ai/policies", {
          params: { query: { limit: 50, offset: 0 } },
        }),
      ),
  });
  const usage = useQuery({
    queryKey: ["admin-ai-usage"],
    queryFn: async () => unwrap(await client.GET("/api/v1/admin/ai/usage")),
  });
  const selectedPolicy = useQuery({
    enabled: selectedPolicyId !== null,
    queryKey: ["admin-ai-policy", selectedPolicyId],
    queryFn: async () =>
      unwrap(
        await client.GET("/api/v1/admin/ai/policies/{feature_policy_id}", {
          params: { path: { feature_policy_id: selectedPolicyId ?? "" } },
        }),
      ),
  });
  const anyPending =
    overview.isPending || policies.isPending || usage.isPending;
  const firstError = overview.error ?? policies.error ?? usage.error;

  return (
    <div className="page admin-page ai-governance-page">
      <PageHeader
        description="Read-only safety, policy, usage, and retrieval visibility. Provider availability is not actively probed."
        eyebrow="Operational oversight"
        title="AI governance"
      />
      {anyPending && (
        <LoadingSkeleton label="Loading AI governance" lines={5} />
      )}
      {firstError && <ErrorSummary error={firstError} />}
      {overview.data && (
        <>
          <section
            className={`ai-safety-banner ai-safety-banner--${aiSafetyPresentation(overview.data.operational_state).tone}`}
            aria-labelledby="ai-effective-state"
          >
            <div>
              <p className="eyebrow">Effective platform state</p>
              <h2 id="ai-effective-state">
                {aiSafetyPresentation(overview.data.operational_state).label}
              </h2>
              <p>{overview.data.operational_explanation}</p>
            </div>
            <AISafetyBadge code={overview.data.operational_state} />
          </section>
          <div className="ai-governance-grid">
            <Panel title="Global safety switch">
              <MetadataGrid
                items={[
                  {
                    label: "Effective state",
                    value: overview.data.global_switch.enabled
                      ? "Enabled"
                      : "Disabled",
                  },
                  { label: "Configuration source", value: "Environment" },
                  { label: "Runtime editing", value: "Unavailable" },
                  { label: "Change requires", value: "Service restart" },
                ]}
              />
              <p className="admin-note">
                Tenant policy cannot override an environment-level disable.
              </p>
            </Panel>
            <Panel title="Retrieval and embeddings">
              <MetadataGrid
                items={[
                  {
                    label: "Embedding provider",
                    value: humanizeCode(
                      overview.data.retrieval.query_embedding_provider.toUpperCase(),
                    ),
                  },
                  {
                    label: "Embedding model",
                    value: overview.data.retrieval.query_embedding_model_code,
                  },
                  {
                    label: "Provider configured",
                    value: overview.data.retrieval.query_embedding_configured
                      ? "Yes"
                      : "No",
                  },
                  {
                    label: "Published retrieval policy",
                    value: overview.data.retrieval
                      .published_configuration_available
                      ? `Version ${String(overview.data.retrieval.version_number)}`
                      : "Unavailable",
                  },
                  {
                    label: "Reranking",
                    value: overview.data.retrieval.reranker_enabled
                      ? overview.data.retrieval.reranker_configured
                        ? "Enabled and configured"
                        : "Enabled, configuration incomplete"
                      : "Disabled",
                  },
                ]}
              />
            </Panel>
          </div>
          <SectionHeader
            description="Safe aliases and deployment state only. Endpoints, credentials, and deployment identifiers are withheld."
            title="Providers and model assignments"
          />
          <div className="ai-provider-grid">
            {overview.data.providers.map((provider) => (
              <article
                className="ai-provider-card"
                key={provider.provider_alias}
              >
                <div className="ai-card-heading">
                  <h3>{humanizeCode(provider.provider_alias.toUpperCase())}</h3>
                  <OutcomeBadge
                    code={provider.configured ? "ALLOWED" : "PARTIAL"}
                  />
                </div>
                <p>{provider.configured ? "Configured" : "Not configured"}</p>
                <CodeChips
                  codes={provider.model_aliases}
                  label={`${provider.provider_alias} model aliases`}
                />
                <small>Availability not probed</small>
              </article>
            ))}
          </div>
          {overview.data.model_assignments.length === 0 ? (
            <EmptyState
              description="No effective published agent model assignments are available."
              title="No model assignments"
            />
          ) : (
            <ul className="ai-assignment-list">
              {overview.data.model_assignments.map((assignment) => (
                <li key={assignment.agent_configuration_version_id}>
                  <div>
                    <strong>{humanizeCode(assignment.agent_code)}</strong>
                    <span>
                      {assignment.provider_alias} / {assignment.model_alias}
                    </span>
                  </div>
                  <AISafetyBadge
                    code={
                      assignment.provider_deployed
                        ? "ready_to_attempt"
                        : "provider_configuration_incomplete"
                    }
                  />
                </li>
              ))}
            </ul>
          )}
          <SectionHeader
            description="Current-process observations reset when this API process restarts. No reset control is available."
            title="Circuit breakers"
          />
          {overview.data.circuits.length === 0 ? (
            <EmptyState
              description="No configured model has been observed by this process."
              title="No circuit observations"
            />
          ) : (
            <ul className="ai-circuit-list">
              {overview.data.circuits.map((circuit) => (
                <li key={`${circuit.provider_alias}-${circuit.model_alias}`}>
                  <div>
                    <strong>
                      {circuit.provider_alias} / {circuit.model_alias}
                    </strong>
                    <span>
                      {circuit.recent_failures} recent failures · current
                      process
                    </span>
                  </div>
                  <AISafetyBadge
                    code={
                      circuit.state === "open" ? "circuit_open" : circuit.state
                    }
                  />
                </li>
              ))}
            </ul>
          )}
        </>
      )}
      {policies.data && (
        <>
          <SectionHeader
            description="Approved policy layers combine at runtime; tenant controls can restrict but never override platform safety."
            title="Policies and budgets"
          />
          {policies.data.items.length === 0 ? (
            <EmptyState title="No visible AI policies" />
          ) : (
            <div className="ai-policy-list">
              {policies.data.items.map((policy) => (
                <article
                  className="ai-policy-card"
                  key={policy.feature_policy_id}
                >
                  <div className="ai-card-heading">
                    <div>
                      <p className="eyebrow">
                        {humanizeCode(policy.scope_type)}
                      </p>
                      <h3>{humanizeCode(policyScope(policy))}</h3>
                    </div>
                    <AISafetyBadge
                      code={
                        policy.approval_status !== "APPROVED"
                          ? "policy_unavailable"
                          : !policy.enabled
                            ? "policy_disabled"
                            : policy.budget_state === "hard_stop"
                              ? "budget_hard_stop"
                              : "ready_to_attempt"
                      }
                    />
                  </div>
                  <MetadataGrid
                    items={[
                      {
                        label: "Approval status",
                        value: humanizeCode(policy.approval_status),
                      },
                      {
                        label: "Daily budget",
                        value:
                          policy.daily_budget && policy.budget_currency
                            ? formatEstimatedCost(
                                policy.daily_budget,
                                policy.budget_currency,
                              )
                            : "Not configured",
                      },
                      {
                        label: "Monthly budget",
                        value:
                          policy.monthly_budget && policy.budget_currency
                            ? formatEstimatedCost(
                                policy.monthly_budget,
                                policy.budget_currency,
                              )
                            : "Not configured",
                      },
                      {
                        label: "Budget state",
                        value: humanizeCode(policy.budget_state),
                      },
                      { label: "Revision", value: policy.row_version },
                    ]}
                  />
                  <Button
                    variant="secondary"
                    onClick={() => {
                      setSelectedPolicyId(policy.feature_policy_id);
                    }}
                  >
                    View policy details
                  </Button>
                </article>
              ))}
            </div>
          )}
          {selectedPolicyId && (
            <Panel className="ai-policy-detail" title="Policy detail">
              {selectedPolicy.isPending && (
                <LoadingSkeleton label="Loading policy detail" />
              )}
              {selectedPolicy.error && (
                <ErrorSummary error={selectedPolicy.error} />
              )}
              {selectedPolicy.data && (
                <MetadataGrid
                  items={[
                    { label: "Scope", value: selectedPolicy.data.scope_type },
                    {
                      label: "Approval status",
                      value: humanizeCode(selectedPolicy.data.approval_status),
                    },
                    {
                      label: "Target",
                      value: policyScope(selectedPolicy.data),
                    },
                    {
                      label: "Maximum input tokens",
                      value:
                        selectedPolicy.data.maximum_input_tokens == null
                          ? "Not configured"
                          : formatTokenCount(
                              selectedPolicy.data.maximum_input_tokens,
                            ),
                    },
                    {
                      label: "Maximum output tokens",
                      value:
                        selectedPolicy.data.maximum_output_tokens == null
                          ? "Not configured"
                          : formatTokenCount(
                              selectedPolicy.data.maximum_output_tokens,
                            ),
                    },
                    {
                      label: "Maximum tool calls",
                      value:
                        selectedPolicy.data.maximum_tool_calls ??
                        "Not configured",
                    },
                    {
                      label: "Requests per user/minute",
                      value:
                        selectedPolicy.data.per_user_requests_per_minute ??
                        "Not configured",
                    },
                    {
                      label: "Effective from",
                      value:
                        selectedPolicy.data.effective_from == null
                          ? "Not bounded"
                          : formatDateTime(selectedPolicy.data.effective_from),
                    },
                    {
                      label: "Effective to",
                      value:
                        selectedPolicy.data.effective_to == null
                          ? "Not bounded"
                          : formatDateTime(selectedPolicy.data.effective_to),
                    },
                  ]}
                />
              )}
            </Panel>
          )}
        </>
      )}
      {usage.data && (
        <>
          <SectionHeader
            description="Completed provider calls from the last seven days. Costs are estimates and remain separated by currency."
            title="Usage"
          />
          {usage.data.totals_by_currency.length === 0 ? (
            <EmptyState
              description="No completed AI provider calls were recorded in this period."
              title="No recorded AI usage"
            />
          ) : (
            <div className="admin-stats ai-usage-stats">
              {usage.data.totals_by_currency.map((total) => (
                <StatCard
                  detail={`${formatTokenCount(total.input_tokens + total.output_tokens)} tokens`}
                  key={total.currency_code}
                  label={`${total.currency_code} estimated spend`}
                  value={formatEstimatedCost(
                    total.estimated_cost,
                    total.currency_code,
                  )}
                />
              ))}
              <StatCard
                label="Completed calls"
                value={usage.data.totals_by_currency.reduce(
                  (sum, total) => sum + total.requests,
                  0,
                )}
              />
            </div>
          )}
          {usage.data.providers.length > 0 && (
            <div className="ai-usage-table-wrap">
              <table className="ai-usage-table">
                <caption>Usage by provider and model</caption>
                <thead>
                  <tr>
                    <th scope="col">Provider and model</th>
                    <th scope="col">Calls</th>
                    <th scope="col">Tokens</th>
                    <th scope="col">Estimated cost</th>
                  </tr>
                </thead>
                <tbody>
                  {usage.data.providers.map((provider) => (
                    <tr
                      key={`${provider.provider_alias}-${provider.model_alias}-${provider.currency_code}`}
                    >
                      <th scope="row">
                        {provider.provider_alias} / {provider.model_alias}
                      </th>
                      <td>{provider.requests}</td>
                      <td>
                        {formatTokenCount(
                          provider.input_tokens + provider.output_tokens,
                        )}
                      </td>
                      <td>
                        {formatEstimatedCost(
                          provider.estimated_cost,
                          provider.currency_code,
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <p className="admin-note">
            Failed and in-flight runs are excluded from spend totals. Historical
            user roles and true use-case dimensions are not stored.
          </p>
        </>
      )}
    </div>
  );
}

type KnowledgeAdminQuery = NonNullable<
  paths["/api/v1/admin/knowledge/documents"]["get"]["parameters"]["query"]
>;
type KnowledgeAdminSummary =
  components["schemas"]["DocumentAdminSummaryResponse"];
interface KnowledgeAdminAction {
  kind: "APPROVE" | "REJECT" | "PUBLISH" | "RETIRE";
  processingVersionId?: string;
}

function knowledgeLifecycleLabel(item: {
  approval_status: string;
  publication_state: string;
}): string {
  if (item.publication_state === "PUBLISHED") return "Published";
  if (item.publication_state === "RETIRED") return "Retired";
  if (item.approval_status === "APPROVED") return "Approved — unpublished";
  return humanizeCode(item.approval_status);
}

function AdminKnowledgePage() {
  const client = useIdentityClient();
  const [search, setSearch] = useState("");
  const [approval, setApproval] = useState("");
  const [publication, setPublication] = useState("");
  const [audience, setAudience] = useState("");
  const [classification, setClassification] = useState("");
  const [page, setPage] = useState(0);
  const limit = 25;
  const documents = useQuery({
    queryKey: [
      "admin-knowledge",
      page,
      search,
      approval,
      publication,
      audience,
      classification,
    ],
    queryFn: async () =>
      unwrap(
        await client.GET("/api/v1/admin/knowledge/documents", {
          params: {
            query: {
              limit,
              offset: page * limit,
              ...(search.trim().length < 2 ? {} : { search: search.trim() }),
              ...(approval === ""
                ? {}
                : {
                    approval_status:
                      approval as KnowledgeAdminQuery["approval_status"],
                  }),
              ...(publication === ""
                ? {}
                : {
                    publication_state:
                      publication as KnowledgeAdminQuery["publication_state"],
                  }),
              ...(audience === ""
                ? {}
                : {
                    audience_code:
                      audience as KnowledgeAdminQuery["audience_code"],
                  }),
              ...(classification === ""
                ? {}
                : {
                    security_classification:
                      classification as KnowledgeAdminQuery["security_classification"],
                  }),
            },
          },
        }),
      ),
  });
  const resetPage = () => {
    setPage(0);
  };
  const columns = [
    {
      header: "Article",
      key: "article",
      render: (row: KnowledgeAdminSummary) => (
        <div className="admin-knowledge-title">
          <Link to={`/admin/knowledge/${row.id}`}>{row.title}</Link>
          <span>{row.source_name}</span>
        </div>
      ),
    },
    {
      header: "Type",
      key: "type",
      render: (row: KnowledgeAdminSummary) =>
        documentTypeLabel(row.document_type),
    },
    {
      header: "Visibility",
      key: "visibility",
      render: (row: KnowledgeAdminSummary) => (
        <span>
          {humanizeCode(row.audience_code)} ·{" "}
          {humanizeCode(row.security_classification)}
        </span>
      ),
    },
    {
      header: "Lifecycle",
      key: "lifecycle",
      render: (row: KnowledgeAdminSummary) => (
        <OutcomeBadge
          code={
            row.publication_state === "PUBLISHED"
              ? "SUCCESS"
              : row.publication_state === "RETIRED" ||
                  row.approval_status === "REJECTED"
                ? "DENIED"
                : "PARTIAL"
          }
        />
      ),
    },
    {
      header: "State",
      key: "state",
      render: (row: KnowledgeAdminSummary) => knowledgeLifecycleLabel(row),
    },
    {
      header: "Version",
      key: "version",
      render: (row: KnowledgeAdminSummary) =>
        row.current_version_number == null
          ? "—"
          : `v${String(row.current_version_number)}`,
    },
    {
      header: "Owner",
      key: "owner",
      render: (row: KnowledgeAdminSummary) => row.owner_group_name ?? "—",
    },
    {
      header: "Updated",
      key: "updated",
      render: (row: KnowledgeAdminSummary) => formatDateTime(row.updated_at),
    },
  ];
  return (
    <div className="page admin-page">
      <PageHeader
        description="Review tenant knowledge, governed versions, visibility, and publication state."
        title="Knowledge"
      />
      <TableToolbar label="Knowledge filters">
        <SearchField
          className="table-search"
          label="Search article titles"
          onChange={(value) => {
            resetPage();
            setSearch(value);
          }}
          placeholder="Enter at least 2 characters"
          value={search}
          withIcon={false}
        />
        <label className="sort-control">
          Publication
          <select
            onChange={(event) => {
              resetPage();
              setPublication(event.target.value);
            }}
            value={publication}
          >
            <option value="">All publication states</option>
            <option value="UNPUBLISHED">Unpublished</option>
            <option value="PUBLISHED">Published</option>
            <option value="RETIRED">Retired</option>
          </select>
        </label>
        <label className="sort-control">
          Approval
          <select
            onChange={(event) => {
              resetPage();
              setApproval(event.target.value);
            }}
            value={approval}
          >
            <option value="">All approval states</option>
            {["DRAFT", "UNDER_REVIEW", "APPROVED", "REJECTED", "RETIRED"].map(
              (value) => (
                <option key={value} value={value}>
                  {humanizeCode(value)}
                </option>
              ),
            )}
          </select>
        </label>
        <label className="sort-control">
          Audience
          <select
            onChange={(event) => {
              resetPage();
              setAudience(event.target.value);
            }}
            value={audience}
          >
            <option value="">All audiences</option>
            {[
              "EMPLOYEE",
              "ANALYST",
              "TECHNICAL_SPECIALIST",
              "ADMIN",
              "ALL",
            ].map((value) => (
              <option key={value} value={value}>
                {humanizeCode(value)}
              </option>
            ))}
          </select>
        </label>
        <label className="sort-control">
          Classification
          <select
            onChange={(event) => {
              resetPage();
              setClassification(event.target.value);
            }}
            value={classification}
          >
            <option value="">All classifications</option>
            {["PUBLIC", "INTERNAL", "CONFIDENTIAL", "RESTRICTED"].map(
              (value) => (
                <option key={value} value={value}>
                  {humanizeCode(value)}
                </option>
              ),
            )}
          </select>
        </label>
      </TableToolbar>
      {search.trim().length === 1 && (
        <p className="admin-note">
          Enter one more character to search article titles.
        </p>
      )}
      {documents.isPending && (
        <LoadingSkeleton label="Loading knowledge articles" />
      )}
      {documents.error && <ErrorSummary error={documents.error} />}
      {documents.data && (
        <>
          <p className="admin-result-count">
            {documents.data.total} tenant articles
          </p>
          <DataTable
            caption="Tenant knowledge articles"
            columns={columns}
            empty={
              <EmptyState
                description="No articles match the current filters."
                title="No knowledge articles"
              />
            }
            getRowKey={(row) => row.id}
            rows={documents.data.items}
          />
          {(page > 0 || documents.data.has_more) && (
            <Pagination
              hasNext={documents.data.has_more}
              onNext={() => {
                setPage((value) => value + 1);
              }}
              onPrevious={() => {
                setPage((value) => Math.max(0, value - 1));
              }}
              page={page + 1}
            />
          )}
        </>
      )}
    </div>
  );
}

function AdminKnowledgeDetailPage() {
  const { documentId = "" } = useParams();
  const client = useIdentityClient();
  const identity = useCurrentIdentity();
  const queryClient = useQueryClient();
  const [action, setAction] = useState<KnowledgeAdminAction | null>(null);
  const [reason, setReason] = useState("");
  const [announcement, setAnnouncement] = useState("");
  const [previewTarget, setPreviewTarget] = useState<{
    versionId: string;
    processingId: string;
  } | null>(null);
  const document = useQuery({
    queryKey: ["admin-knowledge-document", documentId],
    queryFn: async () =>
      unwrap(
        await client.GET("/api/v1/admin/knowledge/documents/{document_id}", {
          params: { path: { document_id: documentId } },
        }),
      ),
  });
  const data = document.data;
  const preview = useQuery({
    queryKey: [
      "admin-knowledge-preview",
      documentId,
      previewTarget?.versionId,
      previewTarget?.processingId,
    ],
    enabled: previewTarget != null,
    queryFn: async () => {
      if (previewTarget == null) throw new Error("Preview target is required.");
      return unwrap(
        await client.GET(
          "/api/v1/admin/knowledge/documents/{document_id}/versions/{version_id}/preview",
          {
            params: {
              path: {
                document_id: documentId,
                version_id: previewTarget.versionId,
              },
              query: {
                processing_version_id: previewTarget.processingId,
                limit: 100,
                offset: 0,
              },
            },
          },
        ),
      );
    },
  });
  const actionMutation = useMutation({
    mutationFn: async (
      requested: KnowledgeAdminAction & { reason: string },
    ) => {
      if (data == null) throw new Error("Knowledge document is unavailable.");
      const header = {
        "Idempotency-Key": newIdempotencyKey(
          `knowledge-${requested.kind.toLowerCase()}`,
        ),
      };
      if (requested.kind === "APPROVE" || requested.kind === "REJECT") {
        return unwrap(
          await client.POST(
            "/api/v1/admin/knowledge/documents/{document_id}/approval-decisions",
            {
              params: { path: { document_id: documentId }, header },
              body: {
                decision:
                  requested.kind === "APPROVE" ? "APPROVED" : "REJECTED",
                expected_version: data.row_version,
                reason: requested.reason,
              },
            },
          ),
        );
      }
      if (requested.kind === "PUBLISH") {
        if (requested.processingVersionId == null)
          throw new Error("A processing version is required.");
        return unwrap(
          await client.POST(
            "/api/v1/admin/knowledge/documents/{document_id}/publication",
            {
              params: { path: { document_id: documentId }, header },
              body: {
                processing_version_id: requested.processingVersionId,
                expected_document_version: data.row_version,
                reason: requested.reason,
              },
            },
          ),
        );
      }
      return unwrap(
        await client.POST(
          "/api/v1/admin/knowledge/documents/{document_id}/retirement",
          {
            params: { path: { document_id: documentId }, header },
            body: {
              expected_version: data.row_version,
              reason: requested.reason,
            },
          },
        ),
      );
    },
    onSuccess: (result, requested) => {
      queryClient.setQueryData(
        ["admin-knowledge-document", documentId],
        result,
      );
      void queryClient.invalidateQueries({ queryKey: ["admin-knowledge"] });
      setAnnouncement(`${humanizeCode(requested.kind)} completed.`);
      setAction(null);
      setReason("");
    },
  });
  const canApprove =
    identity?.permission_codes.includes("KNOWLEDGE_DOCUMENT_APPROVE") ?? false;
  const canPublish =
    identity?.permission_codes.includes("KNOWLEDGE_DOCUMENT_PUBLISH") ?? false;
  const canRetire =
    identity?.permission_codes.includes("KNOWLEDGE_DOCUMENT_RETIRE") ?? false;
  const openAction = (next: KnowledgeAdminAction) => {
    setReason("");
    setAction(next);
  };
  return (
    <div className="page admin-page">
      <Breadcrumbs
        items={[
          { label: "Knowledge", to: "/admin/knowledge" },
          { label: data?.title ?? "Article" },
        ]}
      />
      <p className="sr-only" role="status">
        {announcement}
      </p>
      {document.isPending && (
        <LoadingSkeleton label="Loading knowledge article" />
      )}
      {document.error && <ErrorSummary error={document.error} />}
      {actionMutation.error && <ErrorSummary error={actionMutation.error} />}
      {data && (
        <>
          <PageHeader
            actions={
              <div className="knowledge-admin-actions">
                {canApprove &&
                  data.publication_state === "UNPUBLISHED" &&
                  data.approval_status !== "RETIRED" && (
                    <>
                      <Button
                        onClick={() => {
                          openAction({ kind: "APPROVE" });
                        }}
                      >
                        Approve
                      </Button>
                      <Button
                        onClick={() => {
                          openAction({ kind: "REJECT" });
                        }}
                        variant="danger"
                      >
                        Reject
                      </Button>
                    </>
                  )}
                {canRetire && data.publication_state === "PUBLISHED" && (
                  <Button
                    onClick={() => {
                      openAction({ kind: "RETIRE" });
                    }}
                    variant="danger"
                  >
                    Retire
                  </Button>
                )}
              </div>
            }
            description={`${data.source_name} · ${documentTypeLabel(data.document_type)}`}
            eyebrow={knowledgeLifecycleLabel(data)}
            title={data.title}
          />
          <div className="admin-detail">
            <Panel title="Governance">
              <MetadataGrid
                items={[
                  { label: "Lifecycle", value: knowledgeLifecycleLabel(data) },
                  {
                    label: "Audience",
                    value: humanizeCode(data.audience_code),
                  },
                  {
                    label: "Classification",
                    value: humanizeCode(data.security_classification),
                  },
                  { label: "Owner", value: data.owner_group_name ?? "—" },
                  {
                    label: "Current version",
                    value:
                      data.current_version_number == null
                        ? "None"
                        : `v${String(data.current_version_number)}`,
                  },
                  {
                    label: "Published",
                    value:
                      data.published_at == null
                        ? "—"
                        : formatDateTime(data.published_at),
                  },
                  { label: "Updated", value: formatDateTime(data.updated_at) },
                  { label: "Revision", value: String(data.row_version) },
                ]}
              />
            </Panel>
            <Panel title="Access summary">
              {data.permission_summary.length === 0 ? (
                <p>
                  No explicit document ACL entries. Audience and classification
                  still apply.
                </p>
              ) : (
                <ul className="knowledge-access-summary">
                  {data.permission_summary.map((item) => (
                    <li key={`${item.principal_type}-${item.permission_code}`}>
                      {item.count} {humanizeCode(item.principal_type)} ·{" "}
                      {humanizeCode(item.permission_code)}
                    </li>
                  ))}
                </ul>
              )}
            </Panel>
          </div>
          <SectionHeader title="Versions and processing" />
          <div className="knowledge-version-list">
            {data.versions.map((version) => (
              <article className="knowledge-version-card" key={version.id}>
                <div className="knowledge-version-card__heading">
                  <div>
                    <h3>Version {version.version_number}</h3>
                    <p>
                      {humanizeCode(version.extraction_status)} ·{" "}
                      {humanizeCode(version.validation_status)}
                    </p>
                  </div>
                  {version.current && <OutcomeBadge code="SUCCESS" />}
                </div>
                <ul className="knowledge-processing-list">
                  {version.processing_versions.map((processing) => {
                    const publishable =
                      canPublish &&
                      data.approval_status === "APPROVED" &&
                      data.active &&
                      processing.status === "COMPLETED" &&
                      (processing.validation_status === "PASSED" ||
                        processing.validation_status === "WARNING") &&
                      (processing.chunk_count ?? 0) > 0 &&
                      processing.chunk_count ===
                        processing.embedded_chunk_count &&
                      version.published_processing_version_id !== processing.id;
                    return (
                      <li key={processing.id}>
                        <div>
                          <strong>
                            Processing {processing.processing_number}
                          </strong>
                          <span>
                            {humanizeCode(processing.status)} ·{" "}
                            {humanizeCode(processing.validation_status)} ·{" "}
                            {processing.chunk_count ?? 0} sections
                          </span>
                        </div>
                        <div className="knowledge-processing-actions">
                          <Button
                            onClick={() => {
                              setPreviewTarget({
                                versionId: version.id,
                                processingId: processing.id,
                              });
                            }}
                            variant="secondary"
                          >
                            Preview
                          </Button>
                          {publishable && (
                            <Button
                              onClick={() => {
                                openAction({
                                  kind: "PUBLISH",
                                  processingVersionId: processing.id,
                                });
                              }}
                            >
                              Publish
                            </Button>
                          )}
                        </div>
                      </li>
                    );
                  })}
                </ul>
              </article>
            ))}
          </div>
          {previewTarget && (
            <section
              aria-labelledby="knowledge-preview-heading"
              className="knowledge-preview"
            >
              <SectionHeader title="Content preview" />
              <h2 className="sr-only" id="knowledge-preview-heading">
                Content preview
              </h2>
              {preview.isPending && (
                <LoadingSkeleton label="Loading content preview" />
              )}
              {preview.error && <ErrorSummary error={preview.error} />}
              {preview.data && preview.data.items.length === 0 && (
                <EmptyState description="This processing version contains no preview sections." />
              )}
              {preview.data?.items.map((section) => (
                <article
                  className="knowledge-preview-section"
                  key={section.sequence}
                >
                  <h3>
                    {section.section_title ??
                      section.heading_path ??
                      `Section ${String(section.sequence)}`}
                  </h3>
                  <p>{section.content}</p>
                </article>
              ))}
            </section>
          )}
          <SectionHeader title="Publication history" />
          {data.publication_events.length === 0 ? (
            <EmptyState description="No publication or retirement events are available." />
          ) : (
            <ol className="knowledge-publication-history">
              {data.publication_events.map((event) => (
                <li key={event.id}>
                  <strong>{humanizeCode(event.action_code)}</strong>
                  <span>
                    {formatDateTime(event.occurred_at)} by {event.actor_name}
                  </span>
                </li>
              ))}
            </ol>
          )}
          <ConfirmationDialog
            confirmDisabled={reason.trim().length < 3}
            confirmLabel={
              action == null ? "Confirm" : humanizeCode(action.kind)
            }
            confirmVariant={
              action?.kind === "REJECT" || action?.kind === "RETIRE"
                ? "danger"
                : "primary"
            }
            onCancel={() => {
              setAction(null);
              setReason("");
            }}
            onConfirm={() => {
              if (action != null && reason.trim().length >= 3)
                actionMutation.mutate({ ...action, reason: reason.trim() });
            }}
            open={action != null}
            pending={actionMutation.isPending}
            title={`${action == null ? "Update" : humanizeCode(action.kind)} ${data.title}?`}
          >
            <TextArea
              description="Recorded in the immutable knowledge audit history."
              id="knowledge-action-reason"
              label="Reason"
              maxLength={2000}
              minLength={3}
              onChange={(event) => {
                setReason(event.target.value);
              }}
              required
              rows={4}
              value={reason}
            />
          </ConfirmationDialog>
        </>
      )}
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

function formatDateTime(value: string): string {
  return new Date(value).toLocaleString();
}

function AdminUsersPage() {
  const client = useIdentityClient();
  const [search, setSearch] = useState("");
  const [active, setActive] = useState("");
  const [page, setPage] = useState(0);
  const limit = 25;
  const users = useQuery({
    queryKey: ["admin-users", page, search, active],
    queryFn: async () =>
      unwrap(
        await client.GET("/api/v1/admin/users", {
          params: {
            query: {
              limit,
              offset: page * limit,
              ...(search.trim() === "" ? {} : { search: search.trim() }),
              ...(active === "" ? {} : { active: active === "active" }),
            },
          },
        }),
      ),
  });
  type UserRow = NonNullable<typeof users.data>["items"][number];
  const columns = [
    {
      header: "User",
      key: "user",
      render: (row: UserRow) => (
        <Link to={`/admin/users/${row.user_id}`}>{row.display_name}</Link>
      ),
    },
    {
      header: "Email",
      key: "email",
      render: (row: UserRow) => row.email_address,
    },
    {
      header: "Business unit",
      key: "business-unit",
      render: (row: UserRow) => row.business_unit_name ?? "—",
    },
    {
      header: "Roles",
      key: "roles",
      render: (row: UserRow) => (
        <CodeChips codes={row.role_codes} label="Roles" />
      ),
    },
    {
      header: "Queues",
      key: "queues",
      render: (row: UserRow) =>
        row.support_group_names.length > 0
          ? row.support_group_names.join(", ")
          : "—",
    },
    {
      header: "Status",
      key: "status",
      render: (row: UserRow) => <ActiveBadge active={row.active_flag} />,
    },
  ];
  return (
    <div className="page admin-page">
      <PageHeader
        description="Read-only view of workspace accounts, their roles, and queue membership."
        title="Users"
      />
      <TableToolbar label="User filters">
        <SearchField
          className="table-search"
          label="Search users"
          onChange={(value) => {
            setPage(0);
            setSearch(value);
          }}
          placeholder="Search by name or email"
          value={search}
          withIcon={false}
        />
        <label className="sort-control">
          Status
          <select
            onChange={(event) => {
              setPage(0);
              setActive(event.target.value);
            }}
            value={active}
          >
            <option value="">All statuses</option>
            <option value="active">Active</option>
            <option value="inactive">Inactive</option>
          </select>
        </label>
      </TableToolbar>
      {users.isPending && <LoadingSkeleton label="Loading users" />}
      {users.error && <ErrorSummary error={users.error} />}
      {users.data && (
        <>
          <DataTable
            caption="Workspace users"
            columns={columns}
            empty={
              <EmptyState description="No users match the current filters." />
            }
            getRowKey={(row) => row.user_id}
            rows={users.data.items}
          />
          {(page > 0 || users.data.has_more) && (
            <Pagination
              hasNext={users.data.has_more}
              onNext={() => {
                setPage((value) => value + 1);
              }}
              onPrevious={() => {
                setPage((value) => Math.max(0, value - 1));
              }}
              page={page + 1}
            />
          )}
        </>
      )}
    </div>
  );
}

function AdminUserDetailPage() {
  const { userId = "" } = useParams();
  const client = useIdentityClient();
  const identity = useCurrentIdentity();
  const queryClient = useQueryClient();
  const user = useQuery({
    queryKey: ["admin-user", userId],
    queryFn: async () =>
      unwrap(
        await client.GET("/api/v1/admin/users/{user_id}", {
          params: { path: { user_id: userId } },
        }),
      ),
  });
  const data = user.data;
  const canWrite =
    identity?.permission_codes.includes("ADMIN_IDENTITY_WRITE") ?? false;
  const canMutate = canWrite && identity?.user_id !== userId;
  const [statusDialogOpen, setStatusDialogOpen] = useState(false);
  const [roleToAdd, setRoleToAdd] = useState("");
  const [roleToRemove, setRoleToRemove] = useState<{
    code: string;
    name: string;
  } | null>(null);
  const [announcement, setAnnouncement] = useState("");
  const roleOptions = useQuery({
    queryKey: ["admin-role-options"],
    enabled: canMutate,
    queryFn: async () =>
      unwrap(
        await client.GET("/api/v1/admin/roles", {
          params: { query: { limit: 100 } },
        }),
      ),
  });
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ["admin-user", userId] });
    void queryClient.invalidateQueries({ queryKey: ["admin-users"] });
    void queryClient.invalidateQueries({ queryKey: ["admin-roles"] });
  };
  const statusMutation = useMutation({
    mutationFn: async () => {
      if (!data) throw new Error("User is not loaded");
      return unwrap(
        await client.PATCH("/api/v1/admin/users/{user_id}/status", {
          params: { path: { user_id: userId } },
          body: {
            active: !data.active_flag,
            expected_updated_at: data.updated_at,
          },
        }),
      );
    },
    onSuccess: (result) => {
      setStatusDialogOpen(false);
      setAnnouncement(
        result.active_flag ? "User reactivated." : "User deactivated.",
      );
      refresh();
    },
  });
  const addRoleMutation = useMutation({
    mutationFn: async (roleCode: string) =>
      unwrap(
        await client.POST("/api/v1/admin/users/{user_id}/roles", {
          params: { path: { user_id: userId } },
          body: { role_code: roleCode },
        }),
      ),
    onSuccess: (result) => {
      setRoleToAdd("");
      setAnnouncement(
        result.changed
          ? `Role ${humanizeCode(result.role_code)} assigned.`
          : "Role was already assigned.",
      );
      refresh();
    },
  });
  const removeRoleMutation = useMutation({
    mutationFn: async (roleCode: string) =>
      unwrap(
        await client.DELETE("/api/v1/admin/users/{user_id}/roles/{role_code}", {
          params: { path: { user_id: userId, role_code: roleCode } },
        }),
      ),
    onSuccess: (result) => {
      setRoleToRemove(null);
      setAnnouncement(
        result.changed
          ? `Role ${humanizeCode(result.role_code)} removed.`
          : "Role was not assigned.",
      );
      refresh();
    },
  });
  const mutationError =
    statusMutation.error ?? addRoleMutation.error ?? removeRoleMutation.error;
  return (
    <div className="page admin-page">
      <Breadcrumbs
        items={[
          { label: "Users", to: "/admin/users" },
          { label: data?.display_name ?? "User" },
        ]}
      />
      <p className="sr-only" role="status">
        {announcement}
      </p>
      {user.isPending && <LoadingSkeleton label="Loading user" />}
      {user.error && <ErrorSummary error={user.error} />}
      {mutationError != null && <ErrorSummary error={mutationError} />}
      {data && (
        <>
          <PageHeader
            actions={
              <>
                <ActiveBadge active={data.active_flag} />
                {canMutate && (
                  <Button
                    onClick={() => {
                      statusMutation.reset();
                      setStatusDialogOpen(true);
                    }}
                    variant={data.active_flag ? "danger" : "primary"}
                  >
                    {data.active_flag ? "Deactivate user" : "Reactivate user"}
                  </Button>
                )}
              </>
            }
            description={data.email_address}
            eyebrow="User"
            title={data.display_name}
          />
          <div className="admin-detail">
            <Panel title="Profile">
              <MetadataGrid
                items={[
                  {
                    label: "Business unit",
                    value: data.business_unit_name ?? "—",
                  },
                  { label: "Locale", value: data.locale_code },
                  { label: "Timezone", value: data.timezone_name },
                  {
                    label: "Provisioning",
                    value: humanizeCode(data.provisioning),
                  },
                  {
                    label: "OIDC linked",
                    value: data.oidc_linked ? "Yes" : "No",
                  },
                  { label: "Created", value: formatDateTime(data.created_at) },
                  { label: "Updated", value: formatDateTime(data.updated_at) },
                ]}
              />
            </Panel>
            <Panel title="Effective permissions">
              <CodeChips
                codes={data.effective_permission_codes}
                label="Effective permissions"
              />
            </Panel>
          </div>
          <SectionHeader title="Roles" />
          {canMutate && (
            <TableToolbar label="Role assignment">
              <label className="sort-control">
                Add role
                <select
                  onChange={(event) => {
                    setRoleToAdd(event.target.value);
                  }}
                  value={roleToAdd}
                >
                  <option value="">Choose a role</option>
                  {(roleOptions.data?.items ?? [])
                    .filter((role) => role.active_flag)
                    .map((role) => (
                      <option key={role.role_code} value={role.role_code}>
                        {role.role_name}
                      </option>
                    ))}
                </select>
              </label>
              <Button
                disabled={roleToAdd === "" || addRoleMutation.isPending}
                onClick={() => {
                  addRoleMutation.reset();
                  addRoleMutation.mutate(roleToAdd);
                }}
                variant="secondary"
              >
                Assign role
              </Button>
            </TableToolbar>
          )}
          <DataTable
            caption="Assigned roles"
            columns={[
              {
                header: "Role",
                key: "role",
                render: (row: (typeof data.roles)[number]) => (
                  <Link to={`/admin/roles/${row.role_code}`}>
                    {row.role_name}
                  </Link>
                ),
              },
              {
                header: "Valid from",
                key: "valid-from",
                render: (row: (typeof data.roles)[number]) =>
                  formatDateTime(row.valid_from),
              },
              {
                header: "Valid to",
                key: "valid-to",
                render: (row: (typeof data.roles)[number]) =>
                  row.valid_to ? formatDateTime(row.valid_to) : "—",
              },
              {
                header: "Status",
                key: "status",
                render: (row: (typeof data.roles)[number]) => (
                  <ActiveBadge active={row.active_flag} />
                ),
              },
              ...(canMutate
                ? [
                    {
                      header: "Actions",
                      key: "actions",
                      render: (row: (typeof data.roles)[number]) => (
                        <Button
                          onClick={() => {
                            removeRoleMutation.reset();
                            setRoleToRemove({
                              code: row.role_code,
                              name: row.role_name,
                            });
                          }}
                          variant="secondary"
                        >
                          Remove
                        </Button>
                      ),
                    },
                  ]
                : []),
            ]}
            empty={
              <EmptyState
                description="No roles are assigned."
                title="No roles"
              />
            }
            getRowKey={(row) => row.role_code}
            rows={data.roles}
          />
          <SectionHeader title="Queue memberships" />
          <DataTable
            caption="Queue memberships"
            columns={[
              {
                header: "Queue",
                key: "queue",
                render: (row: (typeof data.memberships)[number]) => (
                  <Link to={`/admin/queues/${row.support_group_id}`}>
                    {row.group_name}
                  </Link>
                ),
              },
              {
                header: "Member role",
                key: "member-role",
                render: (row: (typeof data.memberships)[number]) =>
                  humanizeCode(row.member_role),
              },
              {
                header: "Joined",
                key: "joined",
                render: (row: (typeof data.memberships)[number]) =>
                  formatDateTime(row.joined_at),
              },
              {
                header: "Status",
                key: "status",
                render: (row: (typeof data.memberships)[number]) => (
                  <ActiveBadge active={row.active_flag} />
                ),
              },
            ]}
            empty={
              <EmptyState
                description="This user belongs to no queues."
                title="No queue memberships"
              />
            }
            getRowKey={(row) => row.support_group_id}
            rows={data.memberships}
          />
          <SectionHeader title="Sign-in identities" />
          <DataTable
            caption="External sign-in identities"
            columns={[
              {
                header: "Provider",
                key: "provider",
                render: (row: (typeof data.external_identities)[number]) =>
                  row.provider_code,
              },
              {
                header: "Last authenticated",
                key: "last-authenticated",
                render: (row: (typeof data.external_identities)[number]) =>
                  row.last_authenticated_at
                    ? formatDateTime(row.last_authenticated_at)
                    : "Never",
              },
              {
                header: "Status",
                key: "status",
                render: (row: (typeof data.external_identities)[number]) => (
                  <ActiveBadge active={row.active_flag} />
                ),
              },
            ]}
            empty={
              <EmptyState
                description="No external sign-in identities are linked."
                title="No sign-in identities"
              />
            }
            getRowKey={(row) => row.provider_code}
            rows={data.external_identities}
          />
          <SectionHeader title="Recent security events" />
          {data.recent_security_events.length === 0 && (
            <EmptyState
              description="No security events recorded for this user."
              title="No security events"
            />
          )}
          {data.recent_security_events.length > 0 && (
            <ul className="audit-list">
              {data.recent_security_events.map((item) => (
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
                      {formatDateTime(item.occurred_at)}
                    </time>
                  </div>
                </li>
              ))}
            </ul>
          )}
          <ConfirmationDialog
            confirmLabel={data.active_flag ? "Deactivate" : "Reactivate"}
            confirmVariant={data.active_flag ? "danger" : "primary"}
            onCancel={() => {
              setStatusDialogOpen(false);
            }}
            onConfirm={() => {
              statusMutation.mutate();
            }}
            open={statusDialogOpen}
            pending={statusMutation.isPending}
            title={
              data.active_flag
                ? `Deactivate ${data.display_name}?`
                : `Reactivate ${data.display_name}?`
            }
          >
            <p>
              {data.active_flag
                ? `${data.display_name} will no longer be able to sign in. ` +
                  "Tickets, comments, and history remain unchanged."
                : `${data.display_name} will be able to sign in again with ` +
                  "their existing roles."}
            </p>
          </ConfirmationDialog>
          <ConfirmationDialog
            confirmLabel="Remove role"
            confirmVariant="danger"
            onCancel={() => {
              setRoleToRemove(null);
            }}
            onConfirm={() => {
              if (roleToRemove) removeRoleMutation.mutate(roleToRemove.code);
            }}
            open={roleToRemove !== null}
            pending={removeRoleMutation.isPending}
            title={
              roleToRemove
                ? `Remove the ${roleToRemove.name} role?`
                : "Remove role"
            }
          >
            <p>
              {roleToRemove
                ? `${data.display_name} will lose the ${roleToRemove.name} ` +
                  `role${
                    roleToRemove.code === "PLATFORM_ADMIN"
                      ? " and all administrative access"
                      : ""
                  }.`
                : ""}
            </p>
          </ConfirmationDialog>
        </>
      )}
    </div>
  );
}

function AdminRolesPage() {
  const client = useIdentityClient();
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(0);
  const limit = 25;
  const roles = useQuery({
    queryKey: ["admin-roles", page, search],
    queryFn: async () =>
      unwrap(
        await client.GET("/api/v1/admin/roles", {
          params: {
            query: {
              limit,
              offset: page * limit,
              ...(search.trim() === "" ? {} : { search: search.trim() }),
            },
          },
        }),
      ),
  });
  type RoleRow = NonNullable<typeof roles.data>["items"][number];
  const columns = [
    {
      header: "Role",
      key: "role",
      render: (row: RoleRow) => (
        <Link to={`/admin/roles/${row.role_code}`}>{row.role_name}</Link>
      ),
    },
    {
      header: "Description",
      key: "description",
      render: (row: RoleRow) => row.description ?? "—",
    },
    {
      header: "Type",
      key: "type",
      render: (row: RoleRow) => (row.system_role_flag ? "System" : "Custom"),
    },
    {
      header: "Permissions",
      key: "permissions",
      render: (row: RoleRow) => row.permission_count,
    },
    {
      header: "Assigned users",
      key: "assigned-users",
      render: (row: RoleRow) => row.assigned_user_count,
    },
    {
      header: "Status",
      key: "status",
      render: (row: RoleRow) => <ActiveBadge active={row.active_flag} />,
    },
  ];
  return (
    <div className="page admin-page">
      <PageHeader
        description="Role definitions with their granted permissions and assignments."
        title="Roles"
      />
      <TableToolbar label="Role filters">
        <SearchField
          className="table-search"
          label="Search roles"
          onChange={(value) => {
            setPage(0);
            setSearch(value);
          }}
          placeholder="Search by name or code"
          value={search}
          withIcon={false}
        />
      </TableToolbar>
      {roles.isPending && <LoadingSkeleton label="Loading roles" />}
      {roles.error && <ErrorSummary error={roles.error} />}
      {roles.data && (
        <>
          <DataTable
            caption="Workspace roles"
            columns={columns}
            empty={
              <EmptyState description="No roles match the current filters." />
            }
            getRowKey={(row) => row.role_code}
            rows={roles.data.items}
          />
          {(page > 0 || roles.data.has_more) && (
            <Pagination
              hasNext={roles.data.has_more}
              onNext={() => {
                setPage((value) => value + 1);
              }}
              onPrevious={() => {
                setPage((value) => Math.max(0, value - 1));
              }}
              page={page + 1}
            />
          )}
        </>
      )}
    </div>
  );
}

function AdminRoleDetailPage() {
  const { roleCode = "" } = useParams();
  const client = useIdentityClient();
  const [page, setPage] = useState(0);
  const limit = 25;
  const role = useQuery({
    queryKey: ["admin-role", roleCode, page],
    queryFn: async () =>
      unwrap(
        await client.GET("/api/v1/admin/roles/{role_code}", {
          params: {
            path: { role_code: roleCode },
            query: { limit, offset: page * limit },
          },
        }),
      ),
  });
  const data = role.data;
  return (
    <div className="page admin-page">
      <Breadcrumbs
        items={[
          { label: "Roles", to: "/admin/roles" },
          { label: data?.role_name ?? "Role" },
        ]}
      />
      {role.isPending && <LoadingSkeleton label="Loading role" />}
      {role.error && <ErrorSummary error={role.error} />}
      {data && (
        <>
          <PageHeader
            actions={<ActiveBadge active={data.active_flag} />}
            description={
              data.description ??
              (data.system_role_flag ? "System role" : "Custom role")
            }
            eyebrow={data.system_role_flag ? "System role" : "Custom role"}
            title={data.role_name}
          />
          <SectionHeader title="Permissions" />
          {data.permission_groups.length === 0 && (
            <EmptyState
              description="This role grants no permissions."
              title="No permissions"
            />
          )}
          {data.permission_groups.length > 0 && (
            <div className="permission-groups">
              {data.permission_groups.map((group) => (
                <Panel key={group.domain} title={group.domain}>
                  <CodeChips
                    codes={group.permission_codes}
                    label={`${group.domain} permissions`}
                  />
                </Panel>
              ))}
            </div>
          )}
          <SectionHeader title="Assigned users" />
          <DataTable
            caption="Users assigned to this role"
            columns={[
              {
                header: "User",
                key: "user",
                render: (row: (typeof data.assignments)[number]) => (
                  <Link to={`/admin/users/${row.user_id}`}>
                    {row.display_name}
                  </Link>
                ),
              },
              {
                header: "Email",
                key: "email",
                render: (row: (typeof data.assignments)[number]) =>
                  row.email_address,
              },
              {
                header: "Valid from",
                key: "valid-from",
                render: (row: (typeof data.assignments)[number]) =>
                  formatDateTime(row.valid_from),
              },
              {
                header: "Valid to",
                key: "valid-to",
                render: (row: (typeof data.assignments)[number]) =>
                  row.valid_to ? formatDateTime(row.valid_to) : "—",
              },
              {
                header: "Status",
                key: "status",
                render: (row: (typeof data.assignments)[number]) => (
                  <ActiveBadge active={row.active_flag} />
                ),
              },
            ]}
            empty={
              <EmptyState
                description="No users are assigned to this role."
                title="No assigned users"
              />
            }
            getRowKey={(row) => row.user_id}
            rows={data.assignments}
          />
          {(page > 0 || data.assignments_has_more) && (
            <Pagination
              hasNext={data.assignments_has_more}
              onNext={() => {
                setPage((value) => value + 1);
              }}
              onPrevious={() => {
                setPage((value) => Math.max(0, value - 1));
              }}
              page={page + 1}
            />
          )}
        </>
      )}
    </div>
  );
}

function AdminQueuesPage() {
  const client = useIdentityClient();
  const [search, setSearch] = useState("");
  const [active, setActive] = useState("");
  const [page, setPage] = useState(0);
  const limit = 25;
  const queues = useQuery({
    queryKey: ["admin-queues", page, search, active],
    queryFn: async () =>
      unwrap(
        await client.GET("/api/v1/admin/queues", {
          params: {
            query: {
              limit,
              offset: page * limit,
              ...(search.trim() === "" ? {} : { search: search.trim() }),
              ...(active === "" ? {} : { active: active === "active" }),
            },
          },
        }),
      ),
  });
  type QueueRowData = NonNullable<typeof queues.data>["items"][number];
  const columns = [
    {
      header: "Queue",
      key: "queue",
      render: (row: QueueRowData) => (
        <Link to={`/admin/queues/${row.support_group_id}`}>
          {row.group_name}
        </Link>
      ),
    },
    {
      header: "Code",
      key: "code",
      render: (row: QueueRowData) => row.group_code,
    },
    {
      header: "Contact",
      key: "contact",
      render: (row: QueueRowData) => row.contact_email ?? "—",
    },
    {
      header: "Assignment",
      key: "assignment",
      render: (row: QueueRowData) => humanizeCode(row.assignment_method),
    },
    {
      header: "Members",
      key: "members",
      render: (row: QueueRowData) => row.member_count,
    },
    {
      header: "Status",
      key: "status",
      render: (row: QueueRowData) => <ActiveBadge active={row.active_flag} />,
    },
  ];
  return (
    <div className="page admin-page">
      <PageHeader
        actions={<Link to="/admin/ticket-views">All ticket views</Link>}
        description="Support groups with membership counts and routing configuration."
        title="Queues"
      />
      <TableToolbar label="Queue filters">
        <SearchField
          className="table-search"
          label="Search queues"
          onChange={(value) => {
            setPage(0);
            setSearch(value);
          }}
          placeholder="Search by name or code"
          value={search}
          withIcon={false}
        />
        <label className="sort-control">
          Status
          <select
            onChange={(event) => {
              setPage(0);
              setActive(event.target.value);
            }}
            value={active}
          >
            <option value="">All statuses</option>
            <option value="active">Active</option>
            <option value="inactive">Inactive</option>
          </select>
        </label>
      </TableToolbar>
      {queues.isPending && <LoadingSkeleton label="Loading queues" />}
      {queues.error && <ErrorSummary error={queues.error} />}
      {queues.data && (
        <>
          <DataTable
            caption="Support group queues"
            columns={columns}
            empty={
              <EmptyState description="No queues match the current filters." />
            }
            getRowKey={(row) => row.support_group_id}
            rows={queues.data.items}
          />
          {(page > 0 || queues.data.has_more) && (
            <Pagination
              hasNext={queues.data.has_more}
              onNext={() => {
                setPage((value) => value + 1);
              }}
              onPrevious={() => {
                setPage((value) => Math.max(0, value - 1));
              }}
              page={page + 1}
            />
          )}
        </>
      )}
    </div>
  );
}

const MEMBER_ROLES = ["AGENT", "LEAD", "MANAGER", "OBSERVER"] as const;

function AdminQueueDetailPage() {
  const { supportGroupId = "" } = useParams();
  const client = useIdentityClient();
  const identity = useCurrentIdentity();
  const queryClient = useQueryClient();
  const queue = useQuery({
    queryKey: ["admin-queue", supportGroupId],
    queryFn: async () =>
      unwrap(
        await client.GET("/api/v1/admin/queues/{support_group_id}", {
          params: { path: { support_group_id: supportGroupId } },
        }),
      ),
  });
  const data = queue.data;
  const canWrite =
    identity?.permission_codes.includes("ADMIN_IDENTITY_WRITE") ?? false;
  const [memberToAdd, setMemberToAdd] = useState("");
  const [memberRole, setMemberRole] =
    useState<(typeof MEMBER_ROLES)[number]>("AGENT");
  const [memberToRemove, setMemberToRemove] = useState<{
    userId: string;
    name: string;
  } | null>(null);
  const [announcement, setAnnouncement] = useState("");
  const userOptions = useQuery({
    queryKey: ["admin-member-options"],
    enabled: canWrite,
    queryFn: async () =>
      unwrap(
        await client.GET("/api/v1/admin/users", {
          params: { query: { limit: 100, active: true } },
        }),
      ),
  });
  const refresh = () => {
    void queryClient.invalidateQueries({
      queryKey: ["admin-queue", supportGroupId],
    });
    void queryClient.invalidateQueries({ queryKey: ["admin-queues"] });
    void queryClient.invalidateQueries({ queryKey: ["admin-users"] });
  };
  const addMemberMutation = useMutation({
    mutationFn: async () =>
      unwrap(
        await client.POST("/api/v1/admin/queues/{support_group_id}/members", {
          params: { path: { support_group_id: supportGroupId } },
          body: { user_id: memberToAdd, member_role: memberRole },
        }),
      ),
    onSuccess: (result) => {
      setMemberToAdd("");
      setAnnouncement(
        result.changed ? "Queue member added." : "User is already a member.",
      );
      refresh();
    },
  });
  const removeMemberMutation = useMutation({
    mutationFn: async (memberUserId: string) =>
      unwrap(
        await client.DELETE(
          "/api/v1/admin/queues/{support_group_id}/members/{user_id}",
          {
            params: {
              path: {
                support_group_id: supportGroupId,
                user_id: memberUserId,
              },
            },
          },
        ),
      ),
    onSuccess: (result) => {
      setMemberToRemove(null);
      setAnnouncement(
        result.changed ? "Queue member removed." : "User was not a member.",
      );
      refresh();
    },
  });
  const mutationError = addMemberMutation.error ?? removeMemberMutation.error;
  return (
    <div className="page admin-page">
      <Breadcrumbs
        items={[
          { label: "Queues", to: "/admin/queues" },
          { label: data?.group_name ?? "Queue" },
        ]}
      />
      <p className="sr-only" role="status">
        {announcement}
      </p>
      {queue.isPending && <LoadingSkeleton label="Loading queue" />}
      {queue.error && <ErrorSummary error={queue.error} />}
      {mutationError != null && <ErrorSummary error={mutationError} />}
      {data && (
        <>
          <PageHeader
            actions={<ActiveBadge active={data.active_flag} />}
            description={`Queue code ${data.group_code}`}
            eyebrow="Queue"
            title={data.group_name}
          />
          <Panel title="Details">
            <MetadataGrid
              items={[
                { label: "Contact email", value: data.contact_email ?? "—" },
                {
                  label: "Assignment method",
                  value: humanizeCode(data.assignment_method),
                },
                {
                  label: "Manager",
                  value: data.manager_display_name ?? "—",
                },
                { label: "Created", value: formatDateTime(data.created_at) },
                { label: "Updated", value: formatDateTime(data.updated_at) },
              ]}
            />
          </Panel>
          <SectionHeader title="Members" />
          {canWrite && (
            <TableToolbar label="Queue membership">
              <label className="sort-control">
                Add member
                <select
                  onChange={(event) => {
                    setMemberToAdd(event.target.value);
                  }}
                  value={memberToAdd}
                >
                  <option value="">Choose a user</option>
                  {(userOptions.data?.items ?? []).map((candidate) => (
                    <option key={candidate.user_id} value={candidate.user_id}>
                      {candidate.display_name}
                    </option>
                  ))}
                </select>
              </label>
              <label className="sort-control">
                Member role
                <select
                  onChange={(event) => {
                    setMemberRole(
                      event.target.value as (typeof MEMBER_ROLES)[number],
                    );
                  }}
                  value={memberRole}
                >
                  {MEMBER_ROLES.map((role) => (
                    <option key={role} value={role}>
                      {humanizeCode(role)}
                    </option>
                  ))}
                </select>
              </label>
              <Button
                disabled={memberToAdd === "" || addMemberMutation.isPending}
                onClick={() => {
                  addMemberMutation.reset();
                  addMemberMutation.mutate();
                }}
                variant="secondary"
              >
                Add to queue
              </Button>
            </TableToolbar>
          )}
          <DataTable
            caption="Queue members"
            columns={[
              {
                header: "Member",
                key: "member",
                render: (row: (typeof data.members)[number]) => (
                  <Link to={`/admin/users/${row.user_id}`}>
                    {row.display_name}
                  </Link>
                ),
              },
              {
                header: "Member role",
                key: "member-role",
                render: (row: (typeof data.members)[number]) =>
                  humanizeCode(row.member_role),
              },
              {
                header: "Joined",
                key: "joined",
                render: (row: (typeof data.members)[number]) =>
                  formatDateTime(row.joined_at),
              },
              {
                header: "Status",
                key: "status",
                render: (row: (typeof data.members)[number]) => (
                  <ActiveBadge active={row.active_flag} />
                ),
              },
              ...(canWrite
                ? [
                    {
                      header: "Actions",
                      key: "actions",
                      render: (row: (typeof data.members)[number]) => (
                        <Button
                          onClick={() => {
                            removeMemberMutation.reset();
                            setMemberToRemove({
                              userId: row.user_id,
                              name: row.display_name,
                            });
                          }}
                          variant="secondary"
                        >
                          Remove
                        </Button>
                      ),
                    },
                  ]
                : []),
            ]}
            empty={
              <EmptyState
                description="This queue has no members."
                title="No members"
              />
            }
            getRowKey={(row) => row.user_id}
            rows={data.members}
          />
          <SectionHeader title="Ticket views" />
          <DataTable
            caption="Ticket views owned by this queue"
            columns={[
              {
                header: "View",
                key: "view",
                render: (row: (typeof data.ticket_views)[number]) =>
                  row.queue_name,
              },
              {
                header: "Project",
                key: "project",
                render: (row: (typeof data.ticket_views)[number]) =>
                  row.project_code,
              },
              {
                header: "Visibility",
                key: "visibility",
                render: (row: (typeof data.ticket_views)[number]) =>
                  humanizeCode(row.visibility),
              },
              {
                header: "Order",
                key: "order",
                render: (row: (typeof data.ticket_views)[number]) =>
                  row.display_order,
              },
              {
                header: "Workflow",
                key: "workflow",
                render: (row: (typeof data.ticket_views)[number]) =>
                  row.version_status ? humanizeCode(row.version_status) : "—",
              },
              {
                header: "Status",
                key: "status",
                render: (row: (typeof data.ticket_views)[number]) => (
                  <ActiveBadge active={row.active_flag} />
                ),
              },
            ]}
            empty={
              <EmptyState
                description="No ticket views are owned by this queue."
                title="No ticket views"
              />
            }
            getRowKey={(row) => row.queue_id}
            rows={data.ticket_views}
          />
          <ConfirmationDialog
            confirmLabel="Remove member"
            confirmVariant="danger"
            onCancel={() => {
              setMemberToRemove(null);
            }}
            onConfirm={() => {
              if (memberToRemove)
                removeMemberMutation.mutate(memberToRemove.userId);
            }}
            open={memberToRemove !== null}
            pending={removeMemberMutation.isPending}
            title={
              memberToRemove
                ? `Remove ${memberToRemove.name} from ${data.group_name}?`
                : "Remove member"
            }
          >
            <p>
              {memberToRemove
                ? `Tickets currently assigned to ${memberToRemove.name} stay ` +
                  "assigned and may need manual reassignment."
                : ""}
            </p>
          </ConfirmationDialog>
        </>
      )}
    </div>
  );
}

function AdminTicketViewsPage() {
  const client = useIdentityClient();
  const [page, setPage] = useState(0);
  const limit = 25;
  const views = useQuery({
    queryKey: ["admin-ticket-views", page],
    queryFn: async () =>
      unwrap(
        await client.GET("/api/v1/admin/ticket-views", {
          params: { query: { limit, offset: page * limit } },
        }),
      ),
  });
  type ViewRow = NonNullable<typeof views.data>["items"][number];
  const columns = [
    {
      header: "View",
      key: "view",
      render: (row: ViewRow) => row.queue_name,
    },
    {
      header: "Description",
      key: "description",
      render: (row: ViewRow) => row.description ?? "—",
    },
    {
      header: "Project",
      key: "project",
      render: (row: ViewRow) => row.project_code,
    },
    {
      header: "Visibility",
      key: "visibility",
      render: (row: ViewRow) => humanizeCode(row.visibility),
    },
    {
      header: "Order",
      key: "order",
      render: (row: ViewRow) => row.display_order,
    },
    {
      header: "Workflow",
      key: "workflow",
      render: (row: ViewRow) =>
        row.version_status ? humanizeCode(row.version_status) : "—",
    },
    {
      header: "Status",
      key: "status",
      render: (row: ViewRow) => <ActiveBadge active={row.active_flag} />,
    },
  ];
  return (
    <div className="page admin-page">
      <Breadcrumbs
        items={[
          { label: "Queues", to: "/admin/queues" },
          { label: "Ticket views" },
        ]}
      />
      <PageHeader
        description="Analyst work queues defined across all support groups."
        title="Ticket views"
      />
      {views.isPending && <LoadingSkeleton label="Loading ticket views" />}
      {views.error && <ErrorSummary error={views.error} />}
      {views.data && (
        <>
          <DataTable
            caption="Ticket views"
            columns={columns}
            empty={<EmptyState description="No ticket views are defined." />}
            getRowKey={(row) => row.queue_id}
            rows={views.data.items}
          />
          {(page > 0 || views.data.has_more) && (
            <Pagination
              hasNext={views.data.has_more}
              onNext={() => {
                setPage((value) => value + 1);
              }}
              onPrevious={() => {
                setPage((value) => Math.max(0, value - 1));
              }}
              page={page + 1}
            />
          )}
        </>
      )}
    </div>
  );
}

function AdminWorkflowsPage() {
  const client = useIdentityClient();
  const [search, setSearch] = useState("");
  const [active, setActive] = useState("");
  const [page, setPage] = useState(0);
  const limit = 25;
  const workflows = useQuery({
    queryKey: ["admin-workflows", page, search, active],
    queryFn: async () =>
      unwrap(
        await client.GET("/api/v1/admin/workflows", {
          params: {
            query: {
              limit,
              offset: page * limit,
              ...(search.trim() === "" ? {} : { search: search.trim() }),
              ...(active === "" ? {} : { active: active === "active" }),
            },
          },
        }),
      ),
  });
  type WorkflowRowData = NonNullable<typeof workflows.data>["items"][number];
  const columns = [
    {
      header: "Workflow",
      key: "workflow",
      render: (row: WorkflowRowData) => (
        <Link to={`/admin/workflows/${row.workflow_id}`}>
          {row.workflow_name}
        </Link>
      ),
    },
    {
      header: "Code",
      key: "code",
      render: (row: WorkflowRowData) => row.workflow_code,
    },
    {
      header: "Version",
      key: "version",
      render: (row: WorkflowRowData) =>
        row.current_version_number == null
          ? "—"
          : `v${String(row.current_version_number)} ${humanizeCode(row.current_version_status ?? "")}`,
    },
    {
      header: "Statuses",
      key: "statuses",
      render: (row: WorkflowRowData) => row.status_count,
    },
    {
      header: "Transitions",
      key: "transitions",
      render: (row: WorkflowRowData) => row.transition_count,
    },
    {
      header: "Request types",
      key: "requestTypes",
      render: (row: WorkflowRowData) => row.request_type_count,
    },
    {
      header: "Tickets",
      key: "tickets",
      render: (row: WorkflowRowData) => row.ticket_count,
    },
    {
      header: "Status",
      key: "status",
      render: (row: WorkflowRowData) => (
        <ActiveBadge active={row.active_flag} />
      ),
    },
  ];
  return (
    <div className="page admin-page">
      <PageHeader
        description="Ticket workflows with their published versions, statuses, and transitions. Configuration is read-only."
        title="Workflows"
      />
      <TableToolbar label="Workflow filters">
        <SearchField
          className="table-search"
          label="Search workflows"
          onChange={(value) => {
            setPage(0);
            setSearch(value);
          }}
          placeholder="Search by name or code"
          value={search}
          withIcon={false}
        />
        <label className="sort-control">
          Status
          <select
            onChange={(event) => {
              setPage(0);
              setActive(event.target.value);
            }}
            value={active}
          >
            <option value="">All statuses</option>
            <option value="active">Active</option>
            <option value="inactive">Inactive</option>
          </select>
        </label>
      </TableToolbar>
      {workflows.isPending && <LoadingSkeleton label="Loading workflows" />}
      {workflows.error && <ErrorSummary error={workflows.error} />}
      {workflows.data && (
        <>
          <DataTable
            caption="Ticket workflows"
            columns={columns}
            empty={
              <EmptyState
                description="No workflows match the current filters."
                title="No workflows"
              />
            }
            getRowKey={(row) => row.workflow_id}
            rows={workflows.data.items}
          />
          {(page > 0 || workflows.data.has_more) && (
            <Pagination
              hasNext={workflows.data.has_more}
              onNext={() => {
                setPage((value) => value + 1);
              }}
              onPrevious={() => {
                setPage((value) => Math.max(0, value - 1));
              }}
              page={page + 1}
            />
          )}
        </>
      )}
    </div>
  );
}

const WORKFLOW_DETAIL_TABS = [
  { id: "statuses", label: "Statuses" },
  { id: "transitions", label: "Transitions" },
  { id: "versions", label: "Versions" },
  { id: "request-types", label: "Request types" },
] as const;

function AdminWorkflowDetailPage() {
  const { workflowId = "" } = useParams();
  const client = useIdentityClient();
  const [searchParams, setSearchParams] = useSearchParams();
  const requestedTab = searchParams.get("tab") ?? "statuses";
  const tab = WORKFLOW_DETAIL_TABS.some((item) => item.id === requestedTab)
    ? requestedTab
    : "statuses";
  const workflow = useQuery({
    queryKey: ["admin-workflow", workflowId],
    queryFn: async () =>
      unwrap(
        await client.GET("/api/v1/admin/workflows/{workflow_id}", {
          params: { path: { workflow_id: workflowId } },
        }),
      ),
  });
  const data = workflow.data;
  type StatusRowData = NonNullable<typeof data>["statuses"][number];
  type TransitionRowData = NonNullable<typeof data>["transitions"][number];
  type VersionRowData = NonNullable<typeof data>["versions"][number];
  type MappedRequestTypeData = NonNullable<
    typeof data
  >["request_types"][number];
  const statusColumns = [
    {
      header: "Order",
      key: "order",
      render: (row: StatusRowData) => row.display_order,
    },
    {
      header: "Status",
      key: "status",
      render: (row: StatusRowData) => <StatusBadge status={row.status_code} />,
    },
    {
      header: "Name",
      key: "name",
      render: (row: StatusRowData) => row.status_name,
    },
    {
      header: "Category",
      key: "category",
      render: (row: StatusRowData) => humanizeCode(row.status_category),
    },
    {
      header: "Role",
      key: "role",
      render: (row: StatusRowData) =>
        row.initial_flag ? "Initial" : row.terminal_flag ? "Terminal" : "—",
    },
    {
      header: "Customer label",
      key: "customerLabel",
      render: (row: StatusRowData) => row.customer_visible_name ?? "—",
    },
  ];
  const transitionColumns = [
    {
      header: "Order",
      key: "order",
      render: (row: TransitionRowData) => row.display_order,
    },
    {
      header: "Transition",
      key: "transition",
      render: (row: TransitionRowData) => row.transition_name,
    },
    {
      header: "Path",
      key: "path",
      render: (row: TransitionRowData) =>
        `${row.from_status_name} → ${row.to_status_name}`,
    },
    {
      header: "Guard",
      key: "guard",
      render: (row: TransitionRowData) =>
        row.guard_summary.length === 0 ? "—" : row.guard_summary.join("; "),
    },
    {
      header: "Required fields",
      key: "requiredFields",
      render: (row: TransitionRowData) =>
        row.required_fields.length === 0 ? "—" : row.required_fields.join(", "),
    },
    {
      header: "Actions",
      key: "actions",
      render: (row: TransitionRowData) =>
        row.action_types.length === 0
          ? "—"
          : row.action_types.map((code) => humanizeCode(code)).join(", "),
    },
    {
      header: "Status",
      key: "status",
      render: (row: TransitionRowData) => (
        <ActiveBadge active={row.active_flag} />
      ),
    },
  ];
  const versionColumns = [
    {
      header: "Version",
      key: "version",
      render: (row: VersionRowData) => `v${String(row.version_number)}`,
    },
    {
      header: "Lifecycle",
      key: "lifecycle",
      render: (row: VersionRowData) => humanizeCode(row.version_status),
    },
    {
      header: "Effective from",
      key: "effectiveFrom",
      render: (row: VersionRowData) =>
        row.effective_from == null ? "—" : formatDateTime(row.effective_from),
    },
    {
      header: "Published",
      key: "published",
      render: (row: VersionRowData) =>
        row.published_at == null
          ? "—"
          : `${formatDateTime(row.published_at)}${row.published_by_display_name == null ? "" : ` by ${row.published_by_display_name}`}`,
    },
    {
      header: "Tickets",
      key: "tickets",
      render: (row: VersionRowData) => row.ticket_count,
    },
  ];
  const mappedColumns = [
    {
      header: "Request type",
      key: "requestType",
      render: (row: MappedRequestTypeData) => (
        <Link to={`/admin/catalogue/${row.request_type_id}`}>
          {row.request_type_name}
        </Link>
      ),
    },
    {
      header: "Code",
      key: "code",
      render: (row: MappedRequestTypeData) => row.request_type_code,
    },
    {
      header: "Portal",
      key: "portal",
      render: (row: MappedRequestTypeData) =>
        row.employee_visible_flag ? "Visible" : "Hidden",
    },
    {
      header: "Status",
      key: "status",
      render: (row: MappedRequestTypeData) => (
        <ActiveBadge active={row.active_flag} />
      ),
    },
  ];
  return (
    <div className="page admin-page">
      <Breadcrumbs
        items={[
          { label: "Workflows", to: "/admin/workflows" },
          { label: data?.workflow_name ?? "Workflow" },
        ]}
      />
      {workflow.isPending && <LoadingSkeleton label="Loading workflow" />}
      {workflow.error && <ErrorSummary error={workflow.error} />}
      {data && (
        <>
          <PageHeader
            actions={<ActiveBadge active={data.active_flag} />}
            description={
              data.description ?? `Workflow code ${data.workflow_code}`
            }
            eyebrow="Workflow"
            title={data.workflow_name}
          />
          <Panel title="Details">
            <MetadataGrid
              items={[
                { label: "Workflow code", value: data.workflow_code },
                {
                  label: "Displayed version",
                  value:
                    data.displayed_version_number == null
                      ? "No versions"
                      : `v${String(data.displayed_version_number)} ${humanizeCode(data.displayed_version_status ?? "")}`,
                },
                { label: "Created", value: formatDateTime(data.created_at) },
              ]}
            />
          </Panel>
          <Tabs
            activeId={tab}
            items={[...WORKFLOW_DETAIL_TABS]}
            label="Workflow configuration"
            onChange={(next) => {
              setSearchParams(next === "statuses" ? {} : { tab: next });
            }}
          />
          {tab === "statuses" && (
            <DataTable
              caption="Workflow statuses"
              columns={statusColumns}
              empty={
                <EmptyState
                  description="The displayed version defines no statuses."
                  title="No statuses"
                />
              }
              getRowKey={(row) => row.status_id}
              rows={data.statuses}
            />
          )}
          {tab === "transitions" && (
            <DataTable
              caption="Workflow transitions"
              columns={transitionColumns}
              empty={
                <EmptyState
                  description="The displayed version defines no transitions."
                  title="No transitions"
                />
              }
              getRowKey={(row) => row.transition_id}
              rows={data.transitions}
            />
          )}
          {tab === "versions" && (
            <DataTable
              caption="Workflow versions"
              columns={versionColumns}
              empty={
                <EmptyState
                  description="This workflow has no versions yet."
                  title="No versions"
                />
              }
              getRowKey={(row) => row.workflow_version_id}
              rows={data.versions}
            />
          )}
          {tab === "request-types" && (
            <DataTable
              caption="Request types using this workflow"
              columns={mappedColumns}
              empty={
                <EmptyState
                  description="No request types are mapped to this workflow."
                  title="No mapped request types"
                />
              }
              getRowKey={(row) => row.request_type_id}
              rows={data.request_types}
            />
          )}
        </>
      )}
    </div>
  );
}

function AdminSlaPoliciesPage() {
  const client = useIdentityClient();
  const [search, setSearch] = useState("");
  const [active, setActive] = useState("");
  const [page, setPage] = useState(0);
  const limit = 25;
  const policies = useQuery({
    queryKey: ["admin-sla-policies", page, search, active],
    queryFn: async () =>
      unwrap(
        await client.GET("/api/v1/admin/sla-policies", {
          params: {
            query: {
              limit,
              offset: page * limit,
              ...(search.trim() === "" ? {} : { search: search.trim() }),
              ...(active === "" ? {} : { active: active === "active" }),
            },
          },
        }),
      ),
  });
  type PolicyRowData = NonNullable<typeof policies.data>["items"][number];
  const columns = [
    {
      header: "Policy",
      key: "policy",
      render: (row: PolicyRowData) => (
        <Link to={`/admin/sla-policies/${row.sla_definition_id}`}>
          {row.sla_name}
        </Link>
      ),
    },
    {
      header: "Code",
      key: "code",
      render: (row: PolicyRowData) => row.sla_code,
    },
    {
      header: "Metric",
      key: "metric",
      render: (row: PolicyRowData) => humanizeCode(row.metric_code),
    },
    {
      header: "Project",
      key: "project",
      render: (row: PolicyRowData) => row.project_name,
    },
    {
      header: "Goals",
      key: "goals",
      render: (row: PolicyRowData) => row.goal_count,
    },
    {
      header: "Running",
      key: "running",
      render: (row: PolicyRowData) => row.running_cycle_count,
    },
    {
      header: "Breached",
      key: "breached",
      render: (row: PolicyRowData) => row.breached_cycle_count,
    },
    {
      header: "Status",
      key: "status",
      render: (row: PolicyRowData) => <ActiveBadge active={row.active_flag} />,
    },
  ];
  return (
    <div className="page admin-page">
      <PageHeader
        description="Service level definitions with goals and live cycle activity. Configuration is read-only."
        title="SLA policies"
      />
      <TableToolbar label="SLA policy filters">
        <SearchField
          className="table-search"
          label="Search SLA policies"
          onChange={(value) => {
            setPage(0);
            setSearch(value);
          }}
          placeholder="Search by name or code"
          value={search}
          withIcon={false}
        />
        <label className="sort-control">
          Status
          <select
            onChange={(event) => {
              setPage(0);
              setActive(event.target.value);
            }}
            value={active}
          >
            <option value="">All statuses</option>
            <option value="active">Active</option>
            <option value="inactive">Inactive</option>
          </select>
        </label>
      </TableToolbar>
      {policies.isPending && <LoadingSkeleton label="Loading SLA policies" />}
      {policies.error && <ErrorSummary error={policies.error} />}
      {policies.data && (
        <>
          <DataTable
            caption="SLA policies"
            columns={columns}
            empty={
              <EmptyState
                description="No SLA policies match the current filters."
                title="No SLA policies"
              />
            }
            getRowKey={(row) => row.sla_definition_id}
            rows={policies.data.items}
          />
          {(page > 0 || policies.data.has_more) && (
            <Pagination
              hasNext={policies.data.has_more}
              onNext={() => {
                setPage((value) => value + 1);
              }}
              onPrevious={() => {
                setPage((value) => Math.max(0, value - 1));
              }}
              page={page + 1}
            />
          )}
        </>
      )}
    </div>
  );
}

function ConditionList({ lines, title }: { lines: string[]; title: string }) {
  return (
    <div className="condition-summary">
      <h3>{title}</h3>
      {lines.length === 0 ? (
        <p>—</p>
      ) : (
        <ul>
          {lines.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

function AdminSlaPolicyDetailPage() {
  const { slaDefinitionId = "" } = useParams();
  const client = useIdentityClient();
  const policy = useQuery({
    queryKey: ["admin-sla-policy", slaDefinitionId],
    queryFn: async () =>
      unwrap(
        await client.GET("/api/v1/admin/sla-policies/{sla_definition_id}", {
          params: { path: { sla_definition_id: slaDefinitionId } },
        }),
      ),
  });
  const data = policy.data;
  type GoalRowData = NonNullable<typeof data>["goals"][number];
  type SlaVersionRowData = NonNullable<typeof data>["versions"][number];
  const goalColumns = [
    {
      header: "Goal",
      key: "goal",
      render: (row: GoalRowData) => row.goal_name,
    },
    {
      header: "Target",
      key: "target",
      render: (row: GoalRowData) => formatMinutes(row.target_minutes),
    },
    {
      header: "Warning",
      key: "warning",
      render: (row: GoalRowData) => formatMinutes(row.warning_minutes),
    },
    {
      header: "Calendar",
      key: "calendar",
      render: (row: GoalRowData) => row.calendar_name ?? "—",
    },
    {
      header: "Applies when",
      key: "appliesWhen",
      render: (row: GoalRowData) =>
        row.match_summary.length === 0
          ? "Always"
          : row.match_summary.join("; "),
    },
    {
      header: "Order",
      key: "order",
      render: (row: GoalRowData) => row.priority_order,
    },
    {
      header: "Version",
      key: "version",
      render: (row: GoalRowData) =>
        row.version_number == null
          ? "—"
          : `v${String(row.version_number)} ${humanizeCode(row.version_status ?? "")}`,
    },
    {
      header: "Status",
      key: "status",
      render: (row: GoalRowData) => <ActiveBadge active={row.active_flag} />,
    },
  ];
  const versionColumns = [
    {
      header: "Version",
      key: "version",
      render: (row: SlaVersionRowData) => `v${String(row.version_number)}`,
    },
    {
      header: "Lifecycle",
      key: "lifecycle",
      render: (row: SlaVersionRowData) => humanizeCode(row.version_status),
    },
    {
      header: "Effective from",
      key: "effectiveFrom",
      render: (row: SlaVersionRowData) =>
        row.effective_from == null ? "—" : formatDateTime(row.effective_from),
    },
    {
      header: "Published",
      key: "published",
      render: (row: SlaVersionRowData) =>
        row.published_at == null ? "—" : formatDateTime(row.published_at),
    },
  ];
  return (
    <div className="page admin-page">
      <Breadcrumbs
        items={[
          { label: "SLA policies", to: "/admin/sla-policies" },
          { label: data?.sla_name ?? "SLA policy" },
        ]}
      />
      {policy.isPending && <LoadingSkeleton label="Loading SLA policy" />}
      {policy.error && <ErrorSummary error={policy.error} />}
      {data && (
        <>
          <PageHeader
            actions={<ActiveBadge active={data.active_flag} />}
            description={data.description ?? `SLA code ${data.sla_code}`}
            eyebrow="SLA policy"
            title={data.sla_name}
          />
          <div className="admin-stats">
            <StatCard label="Running" value={data.cycle_counts.running} />
            <StatCard label="Paused" value={data.cycle_counts.paused} />
            <StatCard label="Completed" value={data.cycle_counts.completed} />
            <StatCard label="Breached" value={data.cycle_counts.breached} />
          </div>
          <Panel title="Details">
            <MetadataGrid
              items={[
                { label: "SLA code", value: data.sla_code },
                { label: "Metric", value: humanizeCode(data.metric_code) },
                {
                  label: "Project",
                  value: `${data.project_name} (${data.project_key})`,
                },
                {
                  label: "Pending cycles",
                  value: String(data.cycle_counts.pending),
                },
                {
                  label: "Cancelled cycles",
                  value: String(data.cycle_counts.cancelled),
                },
              ]}
            />
          </Panel>
          <Panel title="Clock conditions">
            <ConditionList
              lines={data.start_condition_summary}
              title="Starts when"
            />
            <ConditionList
              lines={data.pause_condition_summary}
              title="Pauses while"
            />
            <ConditionList
              lines={data.stop_condition_summary}
              title="Stops when"
            />
          </Panel>
          <SectionHeader title="Goals" />
          <DataTable
            caption="SLA goals"
            columns={goalColumns}
            empty={
              <EmptyState
                description="This policy defines no goals."
                title="No goals"
              />
            }
            getRowKey={(row) => row.sla_goal_id}
            rows={data.goals}
          />
          <SectionHeader title="Versions" />
          <DataTable
            caption="SLA policy versions"
            columns={versionColumns}
            empty={
              <EmptyState
                description="This policy has no versions yet."
                title="No policy versions"
              />
            }
            getRowKey={(row) => row.sla_definition_version_id}
            rows={data.versions}
          />
        </>
      )}
    </div>
  );
}

function AdminCalendarsPage() {
  const client = useIdentityClient();
  const [search, setSearch] = useState("");
  const [active, setActive] = useState("");
  const [page, setPage] = useState(0);
  const limit = 25;
  const calendars = useQuery({
    queryKey: ["admin-calendars", page, search, active],
    queryFn: async () =>
      unwrap(
        await client.GET("/api/v1/admin/calendars", {
          params: {
            query: {
              limit,
              offset: page * limit,
              ...(search.trim() === "" ? {} : { search: search.trim() }),
              ...(active === "" ? {} : { active: active === "active" }),
            },
          },
        }),
      ),
  });
  type CalendarRowData = NonNullable<typeof calendars.data>["items"][number];
  const columns = [
    {
      header: "Calendar",
      key: "calendar",
      render: (row: CalendarRowData) => (
        <Link to={`/admin/calendars/${row.calendar_id}`}>
          {row.calendar_name}
        </Link>
      ),
    },
    {
      header: "Code",
      key: "code",
      render: (row: CalendarRowData) => row.calendar_code,
    },
    {
      header: "Timezone",
      key: "timezone",
      render: (row: CalendarRowData) => row.timezone_name,
    },
    {
      header: "Coverage",
      key: "coverage",
      render: (row: CalendarRowData) =>
        row.twenty_four_seven_flag ? "24×7" : "Business hours",
    },
    {
      header: "Version",
      key: "version",
      render: (row: CalendarRowData) =>
        row.current_version_number == null
          ? "—"
          : `v${String(row.current_version_number)} ${humanizeCode(row.current_version_status ?? "")}`,
    },
    {
      header: "Linked goals",
      key: "linkedGoals",
      render: (row: CalendarRowData) => row.linked_goal_count,
    },
    {
      header: "Status",
      key: "status",
      render: (row: CalendarRowData) => (
        <ActiveBadge active={row.active_flag} />
      ),
    },
  ];
  return (
    <div className="page admin-page">
      <PageHeader
        description="Business calendars that drive SLA working-time calculations. Configuration is read-only."
        title="Business calendars"
      />
      <TableToolbar label="Calendar filters">
        <SearchField
          className="table-search"
          label="Search calendars"
          onChange={(value) => {
            setPage(0);
            setSearch(value);
          }}
          placeholder="Search by name or code"
          value={search}
          withIcon={false}
        />
        <label className="sort-control">
          Status
          <select
            onChange={(event) => {
              setPage(0);
              setActive(event.target.value);
            }}
            value={active}
          >
            <option value="">All statuses</option>
            <option value="active">Active</option>
            <option value="inactive">Inactive</option>
          </select>
        </label>
      </TableToolbar>
      {calendars.isPending && <LoadingSkeleton label="Loading calendars" />}
      {calendars.error && <ErrorSummary error={calendars.error} />}
      {calendars.data && (
        <>
          <DataTable
            caption="Business calendars"
            columns={columns}
            empty={
              <EmptyState
                description="No calendars match the current filters."
                title="No calendars"
              />
            }
            getRowKey={(row) => row.calendar_id}
            rows={calendars.data.items}
          />
          {(page > 0 || calendars.data.has_more) && (
            <Pagination
              hasNext={calendars.data.has_more}
              onNext={() => {
                setPage((value) => value + 1);
              }}
              onPrevious={() => {
                setPage((value) => Math.max(0, value - 1));
              }}
              page={page + 1}
            />
          )}
        </>
      )}
    </div>
  );
}

function AdminCalendarDetailPage() {
  const { calendarId = "" } = useParams();
  const client = useIdentityClient();
  const calendar = useQuery({
    queryKey: ["admin-calendar", calendarId],
    queryFn: async () =>
      unwrap(
        await client.GET("/api/v1/admin/calendars/{calendar_id}", {
          params: { path: { calendar_id: calendarId } },
        }),
      ),
  });
  const data = calendar.data;
  type PeriodRowData = NonNullable<typeof data>["working_periods"][number];
  type ExceptionRowData = NonNullable<typeof data>["exceptions"][number];
  type CalendarVersionRowData = NonNullable<typeof data>["versions"][number];
  const periodColumns = [
    {
      header: "Day",
      key: "day",
      render: (row: PeriodRowData) => isoDayName(row.iso_day_of_week),
    },
    {
      header: "Start",
      key: "start",
      render: (row: PeriodRowData) => row.start_local_time,
    },
    {
      header: "End",
      key: "end",
      render: (row: PeriodRowData) => row.end_local_time,
    },
  ];
  const exceptionColumns = [
    {
      header: "Date",
      key: "date",
      render: (row: ExceptionRowData) => row.exception_date,
    },
    {
      header: "Type",
      key: "type",
      render: (row: ExceptionRowData) => humanizeCode(row.exception_type),
    },
    {
      header: "Hours",
      key: "hours",
      render: (row: ExceptionRowData) =>
        row.start_local_time == null || row.end_local_time == null
          ? "Closed"
          : `${row.start_local_time}–${row.end_local_time}`,
    },
    {
      header: "Description",
      key: "description",
      render: (row: ExceptionRowData) => row.description ?? "—",
    },
  ];
  const versionColumns = [
    {
      header: "Version",
      key: "version",
      render: (row: CalendarVersionRowData) => `v${String(row.version_number)}`,
    },
    {
      header: "Lifecycle",
      key: "lifecycle",
      render: (row: CalendarVersionRowData) => humanizeCode(row.version_status),
    },
    {
      header: "Timezone",
      key: "timezone",
      render: (row: CalendarVersionRowData) => row.timezone_name,
    },
    {
      header: "Coverage",
      key: "coverage",
      render: (row: CalendarVersionRowData) =>
        row.twenty_four_seven_flag ? "24×7" : "Business hours",
    },
    {
      header: "Published",
      key: "published",
      render: (row: CalendarVersionRowData) =>
        row.published_at == null ? "—" : formatDateTime(row.published_at),
    },
  ];
  return (
    <div className="page admin-page">
      <Breadcrumbs
        items={[
          { label: "Calendars", to: "/admin/calendars" },
          { label: data?.calendar_name ?? "Calendar" },
        ]}
      />
      {calendar.isPending && <LoadingSkeleton label="Loading calendar" />}
      {calendar.error && <ErrorSummary error={calendar.error} />}
      {data && (
        <>
          <PageHeader
            actions={<ActiveBadge active={data.active_flag} />}
            description={`Calendar code ${data.calendar_code}`}
            eyebrow="Business calendar"
            title={data.calendar_name}
          />
          <Panel title="Details">
            <MetadataGrid
              items={[
                { label: "Timezone", value: data.timezone_name },
                {
                  label: "Coverage",
                  value: data.twenty_four_seven_flag
                    ? "24×7"
                    : "Business hours",
                },
                {
                  label: "Displayed version",
                  value:
                    data.displayed_version_number == null
                      ? "No versions"
                      : `v${String(data.displayed_version_number)} ${humanizeCode(data.displayed_version_status ?? "")}`,
                },
              ]}
            />
          </Panel>
          <SectionHeader title="Working hours" />
          <DataTable
            caption="Calendar working hours"
            columns={periodColumns}
            empty={
              <EmptyState
                description={
                  data.twenty_four_seven_flag
                    ? "This calendar runs around the clock; no working windows apply."
                    : "The displayed version defines no working windows."
                }
                title="No working windows"
              />
            }
            getRowKey={(row) =>
              `${String(row.iso_day_of_week)}-${row.start_local_time}-${row.end_local_time}`
            }
            rows={data.working_periods}
          />
          <SectionHeader title="Holidays and exceptions" />
          <DataTable
            caption="Calendar exceptions"
            columns={exceptionColumns}
            empty={
              <EmptyState
                description="The displayed version defines no holidays or exceptions."
                title="No exceptions"
              />
            }
            getRowKey={(row) => row.exception_date}
            rows={data.exceptions}
          />
          <SectionHeader title="Versions" />
          <DataTable
            caption="Calendar versions"
            columns={versionColumns}
            empty={
              <EmptyState
                description="This calendar has no versions yet."
                title="No calendar versions"
              />
            }
            getRowKey={(row) => row.business_calendar_version_id}
            rows={data.versions}
          />
          <SectionHeader title="Linked SLA goals" />
          {data.linked_goals.length === 0 ? (
            <EmptyState
              description="No SLA goals reference this calendar."
              title="No linked goals"
            />
          ) : (
            <ul
              aria-label="Linked SLA goals"
              className="code-chips code-chips--wrap"
            >
              {data.linked_goals.map((goal) => (
                <li key={`${goal.sla_code}-${goal.goal_name}`}>
                  {goal.sla_code}: {goal.goal_name}
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </div>
  );
}

function AdminCataloguePage() {
  const client = useIdentityClient();
  const [search, setSearch] = useState("");
  const [active, setActive] = useState("");
  const [page, setPage] = useState(0);
  const limit = 25;
  const catalogue = useQuery({
    queryKey: ["admin-catalogue", page, search, active],
    queryFn: async () =>
      unwrap(
        await client.GET("/api/v1/admin/catalogue", {
          params: {
            query: {
              limit,
              offset: page * limit,
              ...(search.trim() === "" ? {} : { search: search.trim() }),
              ...(active === "" ? {} : { active: active === "active" }),
            },
          },
        }),
      ),
  });
  type RequestTypeRowData = NonNullable<typeof catalogue.data>["items"][number];
  const columns = [
    {
      header: "Request type",
      key: "requestType",
      render: (row: RequestTypeRowData) => (
        <Link to={`/admin/catalogue/${row.request_type_id}`}>
          {row.request_type_name}
        </Link>
      ),
    },
    {
      header: "Group",
      key: "group",
      render: (row: RequestTypeRowData) => row.portal_group ?? "—",
    },
    {
      header: "Project",
      key: "project",
      render: (row: RequestTypeRowData) => row.project_key,
    },
    {
      header: "Work type",
      key: "workType",
      render: (row: RequestTypeRowData) => humanizeCode(row.work_type_code),
    },
    {
      header: "Workflow",
      key: "workflow",
      render: (row: RequestTypeRowData) => row.workflow_name,
    },
    {
      header: "Version",
      key: "version",
      render: (row: RequestTypeRowData) =>
        row.current_version_number == null
          ? "—"
          : `v${String(row.current_version_number)} ${humanizeCode(row.current_version_status ?? "")}`,
    },
    {
      header: "Portal",
      key: "portal",
      render: (row: RequestTypeRowData) =>
        row.employee_visible_flag ? "Visible" : "Hidden",
    },
    {
      header: "Status",
      key: "status",
      render: (row: RequestTypeRowData) => (
        <ActiveBadge active={row.active_flag} />
      ),
    },
  ];
  return (
    <div className="page admin-page">
      <PageHeader
        description="Request types offered in the employee portal, with their forms and mappings."
        title="Service catalogue"
      />
      <TableToolbar label="Catalogue filters">
        <SearchField
          className="table-search"
          label="Search catalogue"
          onChange={(value) => {
            setPage(0);
            setSearch(value);
          }}
          placeholder="Search by name or code"
          value={search}
          withIcon={false}
        />
        <label className="sort-control">
          Status
          <select
            onChange={(event) => {
              setPage(0);
              setActive(event.target.value);
            }}
            value={active}
          >
            <option value="">All statuses</option>
            <option value="active">Active</option>
            <option value="inactive">Inactive</option>
          </select>
        </label>
      </TableToolbar>
      {catalogue.isPending && <LoadingSkeleton label="Loading catalogue" />}
      {catalogue.error && <ErrorSummary error={catalogue.error} />}
      {catalogue.data && (
        <>
          <DataTable
            caption="Catalogue request types"
            columns={columns}
            empty={
              <EmptyState
                description="No request types match the current filters."
                title="No request types"
              />
            }
            getRowKey={(row) => row.request_type_id}
            rows={catalogue.data.items}
          />
          {(page > 0 || catalogue.data.has_more) && (
            <Pagination
              hasNext={catalogue.data.has_more}
              onNext={() => {
                setPage((value) => value + 1);
              }}
              onPrevious={() => {
                setPage((value) => Math.max(0, value - 1));
              }}
              page={page + 1}
            />
          )}
        </>
      )}
    </div>
  );
}

function AdminCatalogueDetailPage() {
  const { requestTypeId = "" } = useParams();
  const client = useIdentityClient();
  const identity = useCurrentIdentity();
  const queryClient = useQueryClient();
  const requestType = useQuery({
    queryKey: ["admin-request-type", requestTypeId],
    queryFn: async () =>
      unwrap(
        await client.GET("/api/v1/admin/catalogue/{request_type_id}", {
          params: { path: { request_type_id: requestTypeId } },
        }),
      ),
  });
  const data = requestType.data;
  const canWrite =
    identity?.permission_codes.includes("ADMIN_CONFIG_WRITE") ?? false;
  const [confirming, setConfirming] = useState<"active" | "portal" | null>(
    null,
  );
  const [announcement, setAnnouncement] = useState("");
  const visibilityMutation = useMutation({
    mutationFn: async (change: {
      active: boolean;
      employee_visible: boolean;
    }) =>
      unwrap(
        await client.PATCH(
          "/api/v1/admin/catalogue/{request_type_id}/visibility",
          {
            params: { path: { request_type_id: requestTypeId } },
            body: { ...change, expected_updated_at: data?.updated_at ?? "" },
          },
        ),
      ),
    onSuccess: (result) => {
      setConfirming(null);
      setAnnouncement(
        result.changed
          ? "Request type visibility updated."
          : "No change was needed.",
      );
      void queryClient.invalidateQueries({
        queryKey: ["admin-request-type", requestTypeId],
      });
      void queryClient.invalidateQueries({ queryKey: ["admin-catalogue"] });
    },
  });
  type FormFieldRowData = NonNullable<typeof data>["form_fields"][number];
  type RequestTypeVersionRowData = NonNullable<typeof data>["versions"][number];
  const fieldColumns = [
    {
      header: "Order",
      key: "order",
      render: (row: FormFieldRowData) => row.display_order,
    },
    {
      header: "Field",
      key: "field",
      render: (row: FormFieldRowData) => row.label,
    },
    {
      header: "Code",
      key: "code",
      render: (row: FormFieldRowData) => row.field_code,
    },
    {
      header: "Type",
      key: "type",
      render: (row: FormFieldRowData) => humanizeCode(row.data_type),
    },
    {
      header: "Required",
      key: "required",
      render: (row: FormFieldRowData) => (row.required_flag ? "Required" : "—"),
    },
    {
      header: "Shown when",
      key: "shownWhen",
      render: (row: FormFieldRowData) =>
        row.hidden_flag
          ? "Hidden"
          : row.condition_summary.length === 0
            ? "Always"
            : row.condition_summary.join("; "),
    },
    {
      header: "Options",
      key: "options",
      render: (row: FormFieldRowData) =>
        row.options.length === 0
          ? "—"
          : row.options
              .map(
                (option) =>
                  `${option.option_label}${option.active_flag ? "" : " (inactive)"}`,
              )
              .join(", "),
    },
  ];
  const versionColumns = [
    {
      header: "Version",
      key: "version",
      render: (row: RequestTypeVersionRowData) =>
        `v${String(row.version_number)}`,
    },
    {
      header: "Lifecycle",
      key: "lifecycle",
      render: (row: RequestTypeVersionRowData) =>
        humanizeCode(row.version_status),
    },
    {
      header: "Effective from",
      key: "effectiveFrom",
      render: (row: RequestTypeVersionRowData) =>
        row.effective_from == null ? "—" : formatDateTime(row.effective_from),
    },
    {
      header: "Published",
      key: "published",
      render: (row: RequestTypeVersionRowData) =>
        row.published_at == null ? "—" : formatDateTime(row.published_at),
    },
  ];
  return (
    <div className="page admin-page">
      <Breadcrumbs
        items={[
          { label: "Catalogue", to: "/admin/catalogue" },
          { label: data?.request_type_name ?? "Request type" },
        ]}
      />
      <p className="sr-only" role="status">
        {announcement}
      </p>
      {requestType.isPending && (
        <LoadingSkeleton label="Loading request type" />
      )}
      {requestType.error && <ErrorSummary error={requestType.error} />}
      {visibilityMutation.error != null && (
        <ErrorSummary error={visibilityMutation.error} />
      )}
      {data && (
        <>
          <PageHeader
            actions={
              canWrite ? (
                <>
                  <Button
                    onClick={() => {
                      setConfirming("portal");
                    }}
                    variant="secondary"
                  >
                    {data.employee_visible_flag
                      ? "Hide from portal"
                      : "Show in portal"}
                  </Button>
                  <Button
                    onClick={() => {
                      setConfirming("active");
                    }}
                    variant={data.active_flag ? "danger" : "primary"}
                  >
                    {data.active_flag
                      ? "Disable request type"
                      : "Enable request type"}
                  </Button>
                </>
              ) : (
                <ActiveBadge active={data.active_flag} />
              )
            }
            description={
              data.portal_description ??
              `Request type code ${data.request_type_code}`
            }
            eyebrow="Request type"
            title={data.request_type_name}
          />
          <Panel title="Details">
            <MetadataGrid
              items={[
                { label: "Code", value: data.request_type_code },
                {
                  label: "Project",
                  value: `${data.project_name} (${data.project_key})`,
                },
                {
                  label: "Work type",
                  value: humanizeCode(data.work_type_code),
                },
                { label: "Workflow", value: data.workflow_name },
                { label: "Portal group", value: data.portal_group ?? "—" },
                {
                  label: "Portal visibility",
                  value: data.employee_visible_flag ? "Visible" : "Hidden",
                },
                {
                  label: "Status",
                  value: data.active_flag ? "Active" : "Inactive",
                },
                {
                  label: "Displayed version",
                  value:
                    data.displayed_version_number == null
                      ? "No versions"
                      : `v${String(data.displayed_version_number)} ${humanizeCode(data.displayed_version_status ?? "")}`,
                },
                { label: "Updated", value: formatDateTime(data.updated_at) },
              ]}
            />
          </Panel>
          <SectionHeader title="Request form" />
          <DataTable
            caption="Request form fields"
            columns={fieldColumns}
            empty={
              <EmptyState
                description="The displayed version defines no form fields."
                title="No form fields"
              />
            }
            getRowKey={(row) => row.field_code}
            rows={data.form_fields}
          />
          <SectionHeader title="Versions" />
          <DataTable
            caption="Request type versions"
            columns={versionColumns}
            empty={
              <EmptyState
                description="This request type has no versions yet."
                title="No request type versions"
              />
            }
            getRowKey={(row) => row.request_type_version_id}
            rows={data.versions}
          />
          <ConfirmationDialog
            confirmLabel={data.active_flag ? "Disable" : "Enable"}
            confirmVariant={data.active_flag ? "danger" : "primary"}
            onCancel={() => {
              setConfirming(null);
            }}
            onConfirm={() => {
              visibilityMutation.mutate({
                active: !data.active_flag,
                employee_visible: data.employee_visible_flag,
              });
            }}
            open={confirming === "active"}
            pending={visibilityMutation.isPending}
            title={
              data.active_flag
                ? `Disable ${data.request_type_name}?`
                : `Enable ${data.request_type_name}?`
            }
          >
            {data.active_flag
              ? "Employees will no longer be able to start new requests of this type. Tickets already submitted keep their form and workflow."
              : "Employees will be able to start new requests of this type again."}
          </ConfirmationDialog>
          <ConfirmationDialog
            confirmLabel={data.employee_visible_flag ? "Hide" : "Show"}
            confirmVariant="primary"
            onCancel={() => {
              setConfirming(null);
            }}
            onConfirm={() => {
              visibilityMutation.mutate({
                active: data.active_flag,
                employee_visible: !data.employee_visible_flag,
              });
            }}
            open={confirming === "portal"}
            pending={visibilityMutation.isPending}
            title={
              data.employee_visible_flag
                ? `Hide ${data.request_type_name} from the portal?`
                : `Show ${data.request_type_name} in the portal?`
            }
          >
            {data.employee_visible_flag
              ? "The request type stays active but disappears from the employee portal listing."
              : "The request type will appear in the employee portal listing again."}
          </ConfirmationDialog>
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
          path="/admin/ai"
          element={
            <RequireSession>
              <RequirePermission permission="AI_OVERSIGHT">
                <AdminAIGovernancePage />
              </RequirePermission>
            </RequireSession>
          }
        />
        <Route
          path="/admin/users"
          element={
            <RequireSession>
              <RequirePermission permission="ADMIN_IDENTITY_READ">
                <AdminUsersPage />
              </RequirePermission>
            </RequireSession>
          }
        />
        <Route
          path="/admin/users/:userId"
          element={
            <RequireSession>
              <RequirePermission permission="ADMIN_IDENTITY_READ">
                <AdminUserDetailPage />
              </RequirePermission>
            </RequireSession>
          }
        />
        <Route
          path="/admin/roles"
          element={
            <RequireSession>
              <RequirePermission permission="ADMIN_IDENTITY_READ">
                <AdminRolesPage />
              </RequirePermission>
            </RequireSession>
          }
        />
        <Route
          path="/admin/roles/:roleCode"
          element={
            <RequireSession>
              <RequirePermission permission="ADMIN_IDENTITY_READ">
                <AdminRoleDetailPage />
              </RequirePermission>
            </RequireSession>
          }
        />
        <Route
          path="/admin/queues"
          element={
            <RequireSession>
              <RequirePermission permission="ADMIN_IDENTITY_READ">
                <AdminQueuesPage />
              </RequirePermission>
            </RequireSession>
          }
        />
        <Route
          path="/admin/queues/:supportGroupId"
          element={
            <RequireSession>
              <RequirePermission permission="ADMIN_IDENTITY_READ">
                <AdminQueueDetailPage />
              </RequirePermission>
            </RequireSession>
          }
        />
        <Route
          path="/admin/ticket-views"
          element={
            <RequireSession>
              <RequirePermission permission="ADMIN_IDENTITY_READ">
                <AdminTicketViewsPage />
              </RequirePermission>
            </RequireSession>
          }
        />
        <Route
          path="/admin/workflows"
          element={
            <RequireSession>
              <RequirePermission permission="ADMIN_CONFIG_READ">
                <AdminWorkflowsPage />
              </RequirePermission>
            </RequireSession>
          }
        />
        <Route
          path="/admin/workflows/:workflowId"
          element={
            <RequireSession>
              <RequirePermission permission="ADMIN_CONFIG_READ">
                <AdminWorkflowDetailPage />
              </RequirePermission>
            </RequireSession>
          }
        />
        <Route
          path="/admin/sla-policies"
          element={
            <RequireSession>
              <RequirePermission permission="ADMIN_CONFIG_READ">
                <AdminSlaPoliciesPage />
              </RequirePermission>
            </RequireSession>
          }
        />
        <Route
          path="/admin/sla-policies/:slaDefinitionId"
          element={
            <RequireSession>
              <RequirePermission permission="ADMIN_CONFIG_READ">
                <AdminSlaPolicyDetailPage />
              </RequirePermission>
            </RequireSession>
          }
        />
        <Route
          path="/admin/calendars"
          element={
            <RequireSession>
              <RequirePermission permission="ADMIN_CONFIG_READ">
                <AdminCalendarsPage />
              </RequirePermission>
            </RequireSession>
          }
        />
        <Route
          path="/admin/calendars/:calendarId"
          element={
            <RequireSession>
              <RequirePermission permission="ADMIN_CONFIG_READ">
                <AdminCalendarDetailPage />
              </RequirePermission>
            </RequireSession>
          }
        />
        <Route
          path="/admin/catalogue"
          element={
            <RequireSession>
              <RequirePermission permission="ADMIN_CONFIG_READ">
                <AdminCataloguePage />
              </RequirePermission>
            </RequireSession>
          }
        />
        <Route
          path="/admin/catalogue/:requestTypeId"
          element={
            <RequireSession>
              <RequirePermission permission="ADMIN_CONFIG_READ">
                <AdminCatalogueDetailPage />
              </RequirePermission>
            </RequireSession>
          }
        />
        <Route
          path="/admin/knowledge"
          element={
            <RequireSession>
              <RequirePermission permission="KNOWLEDGE_DOCUMENT_READ_ADMIN">
                <AdminKnowledgePage />
              </RequirePermission>
            </RequireSession>
          }
        />
        <Route
          path="/admin/knowledge/:documentId"
          element={
            <RequireSession>
              <RequirePermission permission="KNOWLEDGE_DOCUMENT_READ_ADMIN">
                <AdminKnowledgeDetailPage />
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
