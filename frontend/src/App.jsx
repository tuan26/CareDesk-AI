import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import Layout from './components/Layout';
import Login from './pages/Login';
import RegisterPage from './pages/RegisterPage';
import Dashboard from './pages/Dashboard';
import ClinicPage from './pages/ClinicPage';
import ServicesPage from './pages/ServicesPage';
import DoctorsPage from './pages/DoctorsPage';
import AppointmentsPage from './pages/AppointmentsPage';
import InboxPage from './pages/InboxPage';
import PatientsPage from './pages/PatientsPage';
import ReportsPage from './pages/ReportsPage';
import PackagesPage from './pages/PackagesPage';
import AutomationPage from './pages/AutomationPage';
import SettingsPage from './pages/SettingsPage';
import PlatformPage from './pages/PlatformPage';
import OrgPage from './pages/OrgPage';
import ClinicChatPage from './pages/ClinicChatPage';
import ChainPage from './pages/ChainPage';

// Protected Route Component to prevent unauthenticated access
const ProtectedRoute = ({ children }) => {
  const token = localStorage.getItem('caredesk_token');
  if (!token) {
    return <Navigate to="/login" replace />;
  }
  return children;
};

function App() {
  return (
    <BrowserRouter>
      <Routes>
        {/* Auth Routes */}
        <Route path="/login" element={<Login />} />
        <Route path="/register" element={<RegisterPage />} />

        {/* Standalone admin consoles (no clinic sidebar) */}
        <Route path="/platform" element={<ProtectedRoute><PlatformPage /></ProtectedRoute>} />
        <Route path="/org" element={<ProtectedRoute><OrgPage /></ProtectedRoute>} />

        {/* Public per-clinic / per-chain links (no login) */}
        <Route path="/c/:slug" element={<ClinicChatPage />} />
        <Route path="/g/:slug" element={<ChainPage />} />

        {/* Dashboard Routes wrapper with Layout and RBAC protection */}
        <Route 
          path="/" 
          element={
            <ProtectedRoute>
              <Layout />
            </ProtectedRoute>
          }
        >
          <Route index element={<Dashboard />} />
          <Route path="clinic" element={<ClinicPage />} />
          <Route path="services" element={<ServicesPage />} />
          <Route path="doctors" element={<DoctorsPage />} />
          <Route path="appointments" element={<AppointmentsPage />} />
          <Route path="inbox" element={<InboxPage />} />
          <Route path="patients" element={<PatientsPage />} />
          <Route path="packages" element={<PackagesPage />} />
          <Route path="automation" element={<AutomationPage />} />
          <Route path="reports" element={<ReportsPage />} />
          <Route path="settings" element={<SettingsPage />} />
        </Route>

        {/* Fallback routing */}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}

export default App;
