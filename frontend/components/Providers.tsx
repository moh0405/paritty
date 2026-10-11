"use client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createContext, useContext, useState, type ReactNode } from "react";
import type { Role } from "@/lib/api";

const RoleContext = createContext<{ role: Role; setRole: (r: Role) => void }>({
  role: "data_manager",
  setRole: () => {},
});
export const useRole = () => useContext(RoleContext);

export function Providers({ children }: { children: ReactNode }) {
  const [client] = useState(() => new QueryClient());
  const [role, setRole] = useState<Role>("data_manager");
  return (
    <QueryClientProvider client={client}>
      <RoleContext.Provider value={{ role, setRole }}>{children}</RoleContext.Provider>
    </QueryClientProvider>
  );
}
