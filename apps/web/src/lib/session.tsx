import {
  createContext,
  type PropsWithChildren,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";

import { apiBaseUrl } from "./api";
import {
  type AuthConfiguration,
  clearTokens,
  fetchAuthConfiguration,
  getAccessToken,
} from "./auth/oidc";

export type Persona = "employee" | "analyst";

export type Session =
  { mode: "developer"; identity: string; persona: Persona } | { mode: "oidc" };

interface SessionContextValue {
  session: Session | null;
  /** undefined while loading, null when the configuration request failed. */
  authConfiguration: AuthConfiguration | null | undefined;
  reloadAuthConfiguration: () => void;
  signIn: (session: { identity: string; persona: Persona }) => void;
  completeOidcSession: () => void;
  signOut: () => void;
}

const storageKey = "fusion-helpdesk-session";
const SessionContext = createContext<SessionContextValue | null>(null);

function storedDeveloperSession(): Session | null {
  try {
    const value = localStorage.getItem(storageKey);
    if (!value) return null;
    const parsed = JSON.parse(value) as {
      identity?: string;
      persona?: Persona;
    };
    if (!parsed.identity || !parsed.persona) return null;
    return {
      mode: "developer",
      identity: parsed.identity,
      persona: parsed.persona,
    };
  } catch {
    return null;
  }
}

function initialSession(): Session | null {
  if (getAccessToken()) return { mode: "oidc" };
  return storedDeveloperSession();
}

export function SessionProvider({ children }: PropsWithChildren) {
  const [session, setSession] = useState<Session | null>(initialSession);
  const [authConfiguration, setAuthConfiguration] = useState<
    AuthConfiguration | null | undefined
  >(undefined);
  const [configurationAttempt, setConfigurationAttempt] = useState(0);
  useEffect(() => {
    let active = true;
    setAuthConfiguration(undefined);
    fetchAuthConfiguration(apiBaseUrl)
      .then((configuration) => {
        if (active) setAuthConfiguration(configuration);
      })
      .catch(() => {
        if (active) setAuthConfiguration(null);
      });
    return () => {
      active = false;
    };
  }, [configurationAttempt]);
  const reloadAuthConfiguration = useCallback(() => {
    setConfigurationAttempt((value) => value + 1);
  }, []);
  // A stored developer session is only valid while the server still allows
  // developer identity; after a posture change (staging/production) the stale
  // session would dead-end on rejected requests, so clear it from server truth.
  useEffect(() => {
    if (
      authConfiguration &&
      !authConfiguration.developer_identity_enabled &&
      session?.mode === "developer"
    ) {
      localStorage.removeItem(storageKey);
      setSession(null);
    }
  }, [authConfiguration, session]);
  const value = useMemo<SessionContextValue>(
    () => ({
      session,
      authConfiguration,
      reloadAuthConfiguration,
      signIn: (next) => {
        localStorage.setItem(storageKey, JSON.stringify(next));
        setSession({ mode: "developer", ...next });
      },
      completeOidcSession: () => {
        setSession(getAccessToken() ? { mode: "oidc" } : null);
      },
      signOut: () => {
        clearTokens();
        localStorage.removeItem(storageKey);
        setSession(null);
      },
    }),
    [session, authConfiguration, reloadAuthConfiguration],
  );
  return (
    <SessionContext.Provider value={value}>{children}</SessionContext.Provider>
  );
}

export function useSession() {
  const value = useContext(SessionContext);
  if (!value) throw new Error("SessionProvider is required.");
  return value;
}

export function sessionHome(session: Session | null): string {
  if (session?.mode === "developer" && session.persona === "analyst")
    return "/agent/tickets";
  return "/portal";
}
