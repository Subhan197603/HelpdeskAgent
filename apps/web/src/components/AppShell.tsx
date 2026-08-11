import { useQuery, useQueryClient } from "@tanstack/react-query";
import type { components } from "@fusion-helpdesk/api-client";
import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { Link, NavLink, useLocation, useNavigate } from "react-router-dom";

import { ApiProblem, sessionApiClient, unwrap } from "../lib/api";
import { useSession } from "../lib/session";
import { Avatar } from "./Avatar";
import { IconButton } from "./Button";
import { Icon, type IconName } from "./Icon";
import { SearchField } from "./SearchField";
import { ErrorState, LoadingSkeleton, UnauthorizedState } from "./States";

type Identity = components["schemas"]["CurrentIdentityResponse"];
type PermissionCode =
  | "ADMIN_IDENTITY_READ"
  | "AUDIT_EVENT_READ"
  | "CATALOG_PROJECT_LIST"
  | "KNOWLEDGE_READ_ANALYST"
  | "KNOWLEDGE_READ_EMPLOYEE"
  | "SYSTEM_HEALTH_READ"
  | "TICKET_ANALYST_READ"
  | "TICKET_DRAFT_CREATE"
  | "TICKET_READ_OWN";

const IdentityContext = createContext<Identity | null>(null);

interface NavigationItem {
  icon: IconName;
  label: string;
  permission: PermissionCode;
  to: string;
}

const employeeNavigation: readonly NavigationItem[] = [
  { icon: "home", label: "Home", permission: "TICKET_READ_OWN", to: "/portal" },
  {
    icon: "catalog",
    label: "Browse services",
    permission: "CATALOG_PROJECT_LIST",
    to: "/portal/catalog",
  },
  {
    icon: "ticket",
    label: "My tickets",
    permission: "TICKET_READ_OWN",
    to: "/portal/requests",
  },
  {
    icon: "book",
    label: "Knowledge base",
    permission: "KNOWLEDGE_READ_EMPLOYEE",
    to: "/portal/knowledge",
  },
];

const analystNavigation: readonly NavigationItem[] = [
  {
    icon: "activity",
    label: "Dashboard",
    permission: "TICKET_ANALYST_READ",
    to: "/agent/dashboard",
  },
  {
    icon: "queue",
    label: "My queues",
    permission: "TICKET_ANALYST_READ",
    to: "/agent/tickets",
  },
  {
    icon: "book",
    label: "Knowledge",
    permission: "KNOWLEDGE_READ_ANALYST",
    to: "/agent/knowledge",
  },
];

const administrationNavigation: readonly NavigationItem[] = [
  {
    icon: "settings",
    label: "Overview",
    permission: "ADMIN_IDENTITY_READ",
    to: "/admin",
  },
  {
    icon: "user",
    label: "Users",
    permission: "ADMIN_IDENTITY_READ",
    to: "/admin/users",
  },
  {
    icon: "shield",
    label: "Roles",
    permission: "ADMIN_IDENTITY_READ",
    to: "/admin/roles",
  },
  {
    icon: "queue",
    label: "Queues",
    permission: "ADMIN_IDENTITY_READ",
    to: "/admin/queues",
  },
  {
    icon: "shield",
    label: "Audit logs",
    permission: "AUDIT_EVENT_READ",
    to: "/admin/audit",
  },
  {
    icon: "activity",
    label: "System status",
    permission: "SYSTEM_HEALTH_READ",
    to: "/admin/system",
  },
];

interface NavigationSection {
  items: readonly NavigationItem[];
  title: string;
}

const navigationSections: readonly NavigationSection[] = [
  { items: employeeNavigation, title: "Workspace" },
  { items: analystNavigation, title: "Analyst tools" },
  { items: administrationNavigation, title: "Administration" },
];

function can(identity: Identity, permission: PermissionCode): boolean {
  return identity.permission_codes.includes(permission);
}

export function useCurrentIdentity() {
  return useContext(IdentityContext);
}

export function RequirePermission({
  children,
  permission,
}: {
  children: ReactNode;
  permission: PermissionCode;
}) {
  const identity = useCurrentIdentity();
  if (!identity || !can(identity, permission))
    return (
      <div className="page">
        <UnauthorizedState />
      </div>
    );
  return children;
}

function ProductMark() {
  return (
    <span aria-hidden="true" className="product-mark">
      <span />
      <span />
    </span>
  );
}

function Sidebar({
  collapsed,
  identity,
  mobileOpen,
  onClose,
  onCollapse,
}: {
  collapsed: boolean;
  identity: Identity;
  mobileOpen: boolean;
  onClose: () => void;
  onCollapse: () => void;
}) {
  const firstLink = useRef<HTMLAnchorElement>(null);
  const sections = navigationSections
    .map((section) => ({
      ...section,
      items: section.items.filter((item) => can(identity, item.permission)),
    }))
    .filter((section) => section.items.length > 0);
  useEffect(() => {
    if (mobileOpen) firstLink.current?.focus();
  }, [mobileOpen]);
  return (
    <>
      {mobileOpen && (
        <button
          aria-label="Close navigation"
          className="nav-scrim"
          onClick={onClose}
          type="button"
        />
      )}
      <aside
        aria-label="Application navigation"
        className={`app-sidebar${collapsed ? " app-sidebar--collapsed" : ""}${mobileOpen ? " app-sidebar--open" : ""}`}
      >
        <Link
          aria-label="HelpdeskAgent"
          className="sidebar-brand"
          onClick={onClose}
          to={
            can(identity, "TICKET_ANALYST_READ") ? "/agent/tickets" : "/portal"
          }
        >
          <ProductMark />
          <span>HelpdeskAgent</span>
        </Link>
        <nav aria-label="Primary navigation" className="sidebar-nav">
          {sections.map((section, sectionIndex) => (
            <div className="sidebar-section" key={section.title}>
              <p>{section.title}</p>
              {section.items.map((item, itemIndex) => (
                <NavLink
                  aria-label={item.label}
                  className={({ isActive }) =>
                    isActive ? "active" : undefined
                  }
                  end={item.to === "/portal" || item.to === "/admin"}
                  key={`${item.label}-${item.to}`}
                  onClick={onClose}
                  ref={
                    sectionIndex === 0 && itemIndex === 0
                      ? firstLink
                      : undefined
                  }
                  title={collapsed ? item.label : undefined}
                  to={item.to}
                >
                  <Icon name={item.icon} />
                  <span>{item.label}</span>
                </NavLink>
              ))}
            </div>
          ))}
        </nav>
        <div className="sidebar-user">
          <Avatar name={identity.display_name} seed={identity.user_id} />
          <div>
            <strong>{identity.display_name}</strong>
            <small>
              {can(identity, "TICKET_ANALYST_READ")
                ? "Analyst workspace"
                : "Employee portal"}
            </small>
          </div>
        </div>
        <button
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          className="sidebar-collapse"
          onClick={onCollapse}
          type="button"
        >
          <Icon name="chevron" />
          <span>{collapsed ? "Expand" : "Collapse"}</span>
        </button>
      </aside>
    </>
  );
}

function TopBar({
  collapsed,
  identity,
  onMenu,
}: {
  collapsed: boolean;
  identity: Identity;
  onMenu: () => void;
}) {
  const { signOut } = useSession();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const location = useLocation();
  const currentLabel =
    navigationSections
      .flatMap((section) => section.items)
      .find((item) => location.pathname.startsWith(item.to))?.label ??
    "Workspace";
  return (
    <header
      className={`app-topbar${collapsed ? " app-topbar--collapsed" : ""}`}
    >
      <IconButton
        className="mobile-menu"
        icon="menu"
        label="Open navigation"
        onClick={onMenu}
      />
      <div className="topbar-context">
        <span>Workspace</span>
        <strong>{currentLabel}</strong>
      </div>
      <SearchField
        disabled
        hint="Ctrl K"
        label="Search tickets and services"
        placeholder="Search tickets and services…"
        title="Global search will be enabled in a future milestone"
      />
      <div className="topbar-actions">
        <IconButton
          disabled
          icon="bell"
          label="Notifications are not yet available"
        />
        <IconButton icon="help" label="Help" />
        <IconButton
          disabled
          icon="settings"
          label="Settings are not yet available"
        />
        <button
          aria-label={`Sign out ${identity.display_name}`}
          className="user-menu"
          onClick={() => {
            queryClient.clear();
            signOut();
            navigate("/login");
          }}
          type="button"
        >
          <Avatar name={identity.display_name} seed={identity.user_id} />
          <span>
            <strong>{identity.display_name}</strong>
            <small>Sign out</small>
          </span>
        </button>
      </div>
    </header>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  const { session, signOut } = useSession();
  const navigate = useNavigate();
  const [collapsed, setCollapsed] = useState(
    () => localStorage.getItem("helpdesk-sidebar-collapsed") === "true",
  );
  const [mobileOpen, setMobileOpen] = useState(false);
  const client = useMemo(() => sessionApiClient(session), [session]);
  const identity = useQuery({
    enabled: Boolean(session),
    queryKey: [
      "current-identity",
      session?.mode,
      session?.mode === "developer" ? session.identity : "oidc",
    ],
    queryFn: async () => unwrap(await client.GET("/api/v1/me")),
  });
  const sessionExpired =
    Boolean(session) &&
    identity.error instanceof ApiProblem &&
    identity.error.status === 401;
  useEffect(() => {
    if (!sessionExpired) return;
    signOut();
    navigate("/login", { replace: true });
  }, [sessionExpired, signOut, navigate]);
  useEffect(() => {
    const close = (event: KeyboardEvent) => {
      if (event.key === "Escape") setMobileOpen(false);
    };
    document.addEventListener("keydown", close);
    return () => {
      document.removeEventListener("keydown", close);
    };
  }, []);
  if (!session) return <main id="main-content">{children}</main>;
  if (identity.isPending)
    return (
      <main className="shell-loading" id="main-content">
        <LoadingSkeleton label="Loading your workspace" lines={5} />
      </main>
    );
  if (identity.isError)
    return (
      <main className="shell-loading" id="main-content">
        <ErrorState description="We could not load your authorized workspace." />
      </main>
    );
  return (
    <IdentityContext.Provider value={identity.data}>
      <a className="skip-link" href="#main-content">
        Skip to content
      </a>
      <Sidebar
        collapsed={collapsed}
        identity={identity.data}
        mobileOpen={mobileOpen}
        onClose={() => {
          setMobileOpen(false);
        }}
        onCollapse={() => {
          setCollapsed((value) => {
            localStorage.setItem("helpdesk-sidebar-collapsed", String(!value));
            return !value;
          });
        }}
      />
      <TopBar
        collapsed={collapsed}
        identity={identity.data}
        onMenu={() => {
          setMobileOpen(true);
        }}
      />
      <main
        className={`app-content${collapsed ? " app-content--collapsed" : ""}`}
        id="main-content"
        tabIndex={-1}
      >
        {children}
      </main>
    </IdentityContext.Provider>
  );
}
