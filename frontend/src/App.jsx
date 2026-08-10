import { BrowserRouter, Routes, Route, Navigate, useParams } from 'react-router-dom';
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
import BookingRequestsPage from './pages/BookingRequestsPage';
import OnboardingPage from './pages/OnboardingPage';


// The old /g/<slug> chain page is now server-rendered at /book/<slug>. That URL
// is outside the SPA, so this needs a real navigation, not a react-router one.
const ToLanding = () => {
  const { slug } = useParams();
  window.location.replace(`/book/${slug}`);
  return null;
};

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

        {/* Protected admin consoles (login required, no clinic sidebar) */}
        <Route path="/platform" element={<ProtectedRoute><PlatformPage /></ProtectedRoute>} />
        <Route path="/org" element={<ProtectedRoute><OrgPage /></ProtectedRoute>} />
        <Route path="/org/:orgSlug" element={<ProtectedRoute><OrgPage /></ProtectedRoute>} />

        {/* Public patient chat (NO login): /chat/<brand>[/<branch>].
            /book/* is NOT routed here — it is server-rendered HTML served by
            FastAPI so link-preview crawlers see real metadata (see
            backend/app/api/endpoints/landing.py). */}
        <Route path="/chat/:brandSlug" element={<ClinicChatPage />} />
        <Route path="/chat/:brandSlug/:branchSlug" element={<ClinicChatPage />} />

        {/* Legacy aliases so previously shared links and printed QR codes keep working */}
        <Route path="/c/:slug" element={<ClinicChatPage />} />
        <Route path="/book/:orgSlug/:clinicSlug/chat" element={<ClinicChatPage />} />
        <Route path="/g/:slug" element={<ToLanding />} />

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
          <Route path="booking-requests" element={<BookingRequestsPage />} />

          <Route path="inbox" element={<InboxPage />} />
          <Route path="patients" element={<PatientsPage />} />
          <Route path="packages" element={<PackagesPage />} />
          <Route path="automation" element={<AutomationPage />} />
          <Route path="reports" element={<ReportsPage />} />
          <Route path="settings" element={<SettingsPage />} />
          <Route path="onboarding" element={<OnboardingPage />} />
        </Route>

        {/* Fallback routing */}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}

export default App;
