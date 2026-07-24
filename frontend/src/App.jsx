/**
 * @file App.jsx
 * @description The root router configuration for the application.
 * Defines all public and protected routes, handles high-level user session state,
 * and controls global login/logout logic.
 */
import React, { useState, Suspense, lazy } from 'react';

const WhatsAppConfig   = lazy(() => import('./components/whatsapp/WhatsAppConfig'));
const WhatsAppFlowList = lazy(() => import('./components/whatsapp/WhatsAppFlowList'));
const WhatsAppFlowEditor = lazy(() => import('./components/whatsapp/WhatsAppFlowEditor'));
import './components/common/AppSideDrawer.css';
import { BrowserRouter as Router, Routes, Route, Navigate, useLocation } from 'react-router-dom';
import Homepage from './components/Homepage';
import Login from './components/Login';
import api from './utils/api';
import Dashboard from './components/Dashboard';
import { GSTRegistrationDetails } from './components/gst_registration/gst_registration';
import GSTRegistrationSignup from './components/gst_registration/GSTRegistrationSignup';
import GSTPersonSignup from './components/gst_registration/GSTPersonSignup';
import UploadDocuments from './components/gst_registration/UploadDocuments';
import PaymentDetails from './components/payments/PaymentDetails';
import CrmDashboard from './components/crm_dashboard/crm_dashboard';
import { prefetchReferenceData, resetReferenceDataPrefetch } from './utils/prefetchReferenceData';
import { clearClientCache } from './utils/clientCache';
import { clearIncomeTaxConfigsCache } from './utils/incomeTaxConfigs';
import {
  startTokenRefreshScheduler,
  stopTokenRefreshScheduler,
  refreshIfStale,
} from './utils/tokenRefreshScheduler';

const MAIN_DASHBOARD_SUB_TABS = new Set([
  'followups',
  'progress',
  'service-done-payment',
  'gst-filing-matrix',
  'today-tasks',
]);

/** Normalize bare /dashboard or invalid dashboard sub before mounting workspace. */
function normalizeMainDashboardSearch(search = '') {
  const params = new URLSearchParams(search);
  const tab = params.get('tab');

  if (!tab) {
    params.set('tab', 'dashboard');
    params.set('sub', 'followups');
    return `?${params.toString()}`;
  }

  if (tab === 'dashboard') {
    const sub = params.get('sub');
    const nextSub = MAIN_DASHBOARD_SUB_TABS.has(sub) ? sub : 'followups';
    if (!sub || sub !== nextSub) {
      params.set('tab', 'dashboard');
      params.set('sub', nextSub);
      return `?${params.toString()}`;
    }
  }

  return null;
}

function DashboardRoute({ onLogout }) {
  const location = useLocation();
  const normalizedSearch = normalizeMainDashboardSearch(location.search);
  if (normalizedSearch && normalizedSearch !== location.search) {
    return <Navigate to={`/dashboard${normalizedSearch}`} replace />;
  }
  return <Dashboard onLogout={onLogout} />;
}

/**
 * Higher-order component representing a protected route.
 * Redirects unauthenticated users to the `/login` page if `session_token` is missing.
 * @param {Object} props.children - The child components to render if authorized.
 */
const ProtectedRoute = ({ children }) => {
  const token = localStorage.getItem('session_token');
  if (!token) return <Navigate to="/login" replace />;
  return children;
};

// --- Cross-tab auth sync ---------------------------------------------------- //
// The active token lives in localStorage, which is shared across every tab of
// the site, so only one account can be "current" at a time. We broadcast REAL
// account changes (explicit login/switch and logout) on a dedicated key so
// other tabs react to those — and NOT to the token churn from proactive refresh
// (same account, rotated token) or the login page clearing a stale token.
const AUTH_EVENT_KEY = 'auth_event';

/** Read the `sub` (emp_id) claim from a JWT without verifying it. */
function readSub(token) {
  if (!token) return null;
  try {
    const part = token.split('.')[1];
    const b64 = part.replace(/-/g, '+').replace(/_/g, '/');
    return JSON.parse(window.atob(b64))?.sub ?? null;
  } catch {
    return null;
  }
}

/** Notify other tabs of a real auth change. `at` guarantees the value changes. */
function broadcastAuthEvent(payload) {
  try {
    localStorage.setItem(AUTH_EVENT_KEY, JSON.stringify({ ...payload, at: Date.now() }));
  } catch {
    /* ignore — best-effort */
  }
}

/**
 * Main application component responsible for initializing global state
 * and routing paths to their specific view components.
 */
function App() {
  // Track if a user is currently logged in, based on the presence of a token
  const [isLoggedIn, setIsLoggedIn] = useState(!!localStorage.getItem('session_token'));

  // The account THIS tab booted as, tracked in memory (not localStorage, which
  // is shared across tabs). Cross-tab auth events compare against this so we can
  // tell a real account switch from same-account token rotation.
  const bootedSubRef = React.useRef(readSub(localStorage.getItem('session_token')));

  // Force re-auth when the refresh token is rejected by the backend.
  const forceReauth = React.useCallback(() => {
    stopTokenRefreshScheduler();
    clearClientCache();
    clearIncomeTaxConfigsCache();
    resetReferenceDataPrefetch();
    localStorage.removeItem('session_token');
    bootedSubRef.current = null;
    setIsLoggedIn(false);
    if (window.location.pathname !== '/login') {
      window.location.href = '/login';
    }
  }, []);

  // Cross-tab auth sync: react to explicit login/logout broadcast by OTHER tabs.
  React.useEffect(() => {
    const onStorage = (e) => {
      if (e.key !== AUTH_EVENT_KEY || !e.newValue) return;
      let evt;
      try { evt = JSON.parse(e.newValue); } catch { return; }
      if (evt.type === 'logout') {
        // Logged out in another tab → drop this tab's session too.
        if (bootedSubRef.current) forceReauth();
      } else if (evt.type === 'login') {
        // Another tab logged in / switched. If it's a DIFFERENT account, this
        // tab is now showing stale data for the wrong user (localStorage token
        // is shared) — reload to re-bootstrap as the now-active account.
        if (bootedSubRef.current && String(evt.sub) !== String(bootedSubRef.current)) {
          window.location.reload();
        }
      }
    };
    window.addEventListener('storage', onStorage);
    return () => window.removeEventListener('storage', onStorage);
  }, [forceReauth]);

  // On app load with an existing session (e.g. page refresh): warm the cache,
  // start the proactive token-refresh loop, and refresh on tab focus.
  React.useEffect(() => {
    if (!localStorage.getItem('session_token')) return undefined;

    prefetchReferenceData();
    startTokenRefreshScheduler({ onAuthFailure: forceReauth });

    const handleVisibility = () => {
      if (document.visibilityState === 'visible') {
        refreshIfStale();
      }
    };
    document.addEventListener('visibilitychange', handleVisibility);
    return () => {
      document.removeEventListener('visibilitychange', handleVisibility);
    };
    // Re-run on login (isLoggedIn) as well as mount: a fresh in-session login
    // sets the token AFTER this effect first ran with no token and bailed, so
    // without isLoggedIn the wake/focus refresh handler would never attach for
    // that session until a full page reload. startTokenRefreshScheduler clears
    // its own prior timer, so re-running it is safe.
  }, [forceReauth, isLoggedIn]);

  /**
   * Called upon successful login/signup to store the token and update state.
   * @param {string} token - The JWT authentication token.
   */
  const handleLoginSignupSuccess = (token) => {
    if (token) localStorage.setItem('session_token', token);
    bootedSubRef.current = readSub(token);
    // Tell other tabs an account just became active here. If they were showing
    // a different account, they'll reload; same account → they ignore it.
    broadcastAuthEvent({ type: 'login', sub: readSub(token) });
    setIsLoggedIn(true);
    // Warm shared reference data in the background so the first navigation
    // into those screens is instant (no per-click fetch lag).
    prefetchReferenceData({ force: true });
    // Proactively refresh the access token before it expires.
    startTokenRefreshScheduler({ onAuthFailure: forceReauth });
  };

  /**
   * Revokes the session by notifying the backend and clearing local storage.
   */
  const handleLogout = React.useCallback(async () => {
    try {
      await api.post('/app/v1/logout');
    } catch (err) {
      // Silently fail logout if backend unreachable or already 401
    }
    localStorage.removeItem('session_token');
    bootedSubRef.current = null;
    // Stop the proactive refresh loop and wipe cached reference data.
    stopTokenRefreshScheduler();
    clearClientCache();
    clearIncomeTaxConfigsCache();
    resetReferenceDataPrefetch();
    // Tell other tabs to log out too.
    broadcastAuthEvent({ type: 'logout' });
    setIsLoggedIn(false);
  }, []);

  return (
    <Router>
      <div>
        <Routes>
          <Route path="/" element={<Homepage />} />
          <Route path="/login" element={<Login onSuccess={handleLoginSignupSuccess} />} />
          <Route
            path="/dashboard"
            element={
              <ProtectedRoute>
                <DashboardRoute onLogout={handleLogout} />
              </ProtectedRoute>
            }
          />
          <Route
            path="/gst-registrations/new"
            element={
              <ProtectedRoute>
                <GSTRegistrationSignup onLogout={handleLogout} />
              </ProtectedRoute>
            }
          />
          <Route
            path="/gst-registration-details"
            element={
              <ProtectedRoute>
                <GSTRegistrationDetails onLogout={handleLogout} />
              </ProtectedRoute>
            }
          />
          <Route
            path="/gst-person-details"
            element={
              <ProtectedRoute>
                <Navigate to="/dashboard?tab=gst&sub=people" replace />
              </ProtectedRoute>
            }
          />
          <Route
            path="/gst-document-details"
            element={
              <ProtectedRoute>
                <Navigate to="/dashboard?tab=gst&sub=documents" replace />
              </ProtectedRoute>
            }
          />
          <Route
            path="/gst-person-signup"
            element={
              <ProtectedRoute>
                <GSTPersonSignup onLogout={handleLogout} />
              </ProtectedRoute>
            }
          />
          <Route
            path="/upload-documents"
            element={
              <ProtectedRoute>
                <UploadDocuments onLogout={handleLogout} />
              </ProtectedRoute>
            }
          />
          <Route
            path="/payment-details/:paymentId"
            element={
              <ProtectedRoute>
                <PaymentDetails onLogout={handleLogout} />
              </ProtectedRoute>
            }
          />
          <Route
            path="/crm-dashboard"
            element={
              <ProtectedRoute>
                <CrmDashboard onLogout={handleLogout} />
              </ProtectedRoute>
            }
          />
          <Route
            path="/whatsapp"
            element={
              <ProtectedRoute>
                <Suspense fallback={null}>
                  <WhatsAppConfig />
                </Suspense>
              </ProtectedRoute>
            }
          />
          <Route
            path="/whatsapp-flows"
            element={
              <ProtectedRoute>
                <Suspense fallback={null}>
                  <WhatsAppFlowList />
                </Suspense>
              </ProtectedRoute>
            }
          />
          <Route
            path="/whatsapp-flows/:id"
            element={
              <ProtectedRoute>
                <Suspense fallback={null}>
                  <WhatsAppFlowEditor />
                </Suspense>
              </ProtectedRoute>
            }
          />
        </Routes>
      </div>
    </Router>
  );
}

export default App;
