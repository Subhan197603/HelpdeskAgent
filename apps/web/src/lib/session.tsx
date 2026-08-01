import {
  createContext,
  type PropsWithChildren,
  useContext,
  useMemo,
  useState,
} from "react";

export type Persona = "employee" | "analyst";

interface Session {
  identity: string;
  persona: Persona;
}

interface SessionContextValue {
  session: Session | null;
  signIn: (session: Session) => void;
  signOut: () => void;
}

const storageKey = "fusion-helpdesk-session";
const SessionContext = createContext<SessionContextValue | null>(null);

function storedSession(): Session | null {
  try {
    const value = localStorage.getItem(storageKey);
    return value ? (JSON.parse(value) as Session) : null;
  } catch {
    return null;
  }
}

export function SessionProvider({ children }: PropsWithChildren) {
  const [session, setSession] = useState<Session | null>(storedSession);
  const value = useMemo<SessionContextValue>(
    () => ({
      session,
      signIn: (next) => {
        localStorage.setItem(storageKey, JSON.stringify(next));
        setSession(next);
      },
      signOut: () => {
        localStorage.removeItem(storageKey);
        setSession(null);
      },
    }),
    [session],
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
