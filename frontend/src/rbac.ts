import type { UserRole } from "./types";

export type NavRoute = {
  to:    string;
  label: string;
  roles: UserRole[];  // empty = all roles
};

const ALL: UserRole[] = [
  "STATE_ADMIN", "DISTRICT_ADMIN", "MANDAL_ADMIN",
  "AFSO", "FPS_DEALER", "RATION_CARD_HOLDER",
];

const STAFF: UserRole[] = [
  "STATE_ADMIN", "DISTRICT_ADMIN", "MANDAL_ADMIN", "AFSO",
];

export const NAV_ROUTES: NavRoute[] = [
  { to: "/",               label: "Overview",     roles: [...STAFF, "FPS_DEALER"] },
  { to: "/distribution",   label: "Distribution", roles: [...STAFF, "FPS_DEALER"] },
  { to: "/smart-allot",    label: "SMARTAllot",   roles: STAFF },
  { to: "/model-overview", label: "Command Map",  roles: STAFF },
  { to: "/anomalies",      label: "Anomalies",    roles: STAFF },
  { to: "/call-centre",    label: "Call Centre",  roles: ALL },
  { to: "/tickets",        label: "Tickets",      roles: ALL },
  { to: "/users",          label: "Users",        roles: STAFF },
  { to: "/settings",       label: "Settings",     roles: ALL },
];

export function canAccess(role: UserRole, path: string): boolean {
  const route = NAV_ROUTES.find(r => r.to === path);
  if (!route) return false;
  return route.roles.includes(role);
}

/** The first route a role is allowed to land on after login. */
export function defaultRoute(role: UserRole): string {
  const first = NAV_ROUTES.find(r => r.roles.includes(role));
  return first?.to ?? "/bot";
}
