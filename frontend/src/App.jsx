/**
 * @file App.jsx
 * @description The root router configuration for the application. 
 * Defines all public and protected routes, handles high-level user session state, 
 * and controls global login/logout logic.
 */
import React, { useState } from 'react';
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

/**
 * Main application component responsible for initializing global state 
 * and routing paths to their specific view components.
 */
function App() {
  // Track if a user is currently logged in, based on the presence of a token
  const [isLoggedIn, setIsLoggedIn] = useState(!!localStorage.getItem('session_token'));

  // Force re-auth when the refresh token is rejected by the backend.
  const forceReauth = React.useCallback(() => {
    stopTokenRefreshScheduler();
    clearClientCache();
    clearIncomeTaxConfigsCache();
    resetReferenceDataPrefetch();
    localStorage.removeItem('session_token');
    localStorage.removeItem('refresh_token');
    setIsLoggedIn(false);
    if (window.location.pathname !== '/login') {
      window.location.href = '/login';
    }
  }, []);

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
  }, [forceReauth]);

  /**
   * Called upon successful login/signup to store the token and update state.
   * @param {string} token - The JWT authentication token.
   */
  const handleLoginSignupSuccess = (token) => {
    if (token) localStorage.setItem('session_token', token);
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
    localStorage.removeItem('refresh_token');
    // Stop the proactive refresh loop and wipe cached reference data.
    stopTokenRefreshScheduler();
    clearClientCache();
    clearIncomeTaxConfigsCache();
    resetReferenceDataPrefetch();
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
        </Routes>
      </div>
    </Router>
  );
}

export default App;
