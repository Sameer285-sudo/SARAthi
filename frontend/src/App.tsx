import { Navigate, Route, Routes } from "react-router-dom";
import { Shell } from "./components/Shell";
import { useAuth } from "./context/AuthContext";
import { canAccess, defaultRoute } from "./rbac";
import { AnomaliesPage } from "./pages/AnomaliesPage";
import { DistributionPage } from "./pages/DistributionPage";
import { CallCentrePage } from "./pages/CallCentrePage";
import LoginPage from "./pages/LoginPage";
import { OverviewPage } from "./pages/OverviewPage";
import { SmartAllotPage } from "./pages/SmartAllotPage";
import { ModelOverviewPage } from "./pages/ModelOverviewPage";
import { TicketsPage } from "./pages/TicketsPage";
import { UsersPage } from "./pages/UsersPage";
import { SettingsPage } from "./pages/SettingsPage";
import type { UserRole } from "./types";

function RoleRoute({ path, element, role }: { path: string; element: JSX.Element; role: UserRole }) {
  if (!canAccess(role, path)) {
    return <Navigate to={defaultRoute(role)} replace />;
  }
  return element;
}

function ProtectedRoutes() {
  const { isAuth, user } = useAuth();
  if (!isAuth || !user) return <Navigate to="/login" replace />;

  const role = user.role;

  return (
    <Shell>
      <Routes>
        <Route path="/"               element={<RoleRoute path="/"               role={role} element={<OverviewPage />}    />} />
        <Route path="/distribution"   element={<RoleRoute path="/distribution"   role={role} element={<DistributionPage />} />} />
        <Route path="/smart-allot"    element={<RoleRoute path="/smart-allot"    role={role} element={<SmartAllotPage />}  />} />
        <Route path="/model-overview" element={<RoleRoute path="/model-overview" role={role} element={<ModelOverviewPage />}/>} />
        <Route path="/anomalies"      element={<RoleRoute path="/anomalies"      role={role} element={<AnomaliesPage />}   />} />
        <Route path="/call-centre" element={<RoleRoute path="/call-centre" role={role} element={<CallCentrePage />}  />} />
        <Route path="/tickets"     element={<RoleRoute path="/tickets"     role={role} element={<TicketsPage />}     />} />
        <Route path="/users"       element={<RoleRoute path="/users"       role={role} element={<UsersPage />}       />} />
        <Route path="/settings"    element={<RoleRoute path="/settings"    role={role} element={<SettingsPage />}    />} />
        <Route path="*"            element={<Navigate to={defaultRoute(role)} replace />} />
      </Routes>
    </Shell>
  );
}

export default function App() {
  const { isAuth, user } = useAuth();
  return (
    <Routes>
      <Route
        path="/login"
        element={isAuth && user ? <Navigate to={defaultRoute(user.role)} replace /> : <LoginPage />}
      />
      <Route path="/*" element={<ProtectedRoutes />} />
    </Routes>
  );
}
