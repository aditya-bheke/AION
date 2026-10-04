import { createContext, useContext } from "react";

// The signed-in user, provided by <App> and read by any component that needs it.
export const UserContext = createContext(null);
export const useUser = () => useContext(UserContext);

// Mirrors the backend role order. The UI only hides actions; the API enforces them.
const RANK = { viewer: 0, engineer: 1, approver: 2, admin: 3 };
export const hasRole = (user, role) => !!user && RANK[user.role] >= RANK[role];
