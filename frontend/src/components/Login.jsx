/**
 * @file Login.jsx
 * @description Provides the authentication UI for employees and admins.
 * Supports standard credential-based authentication as well as an OTP-based
 * password reset flow via the Twilio SMS service integration.
 */
import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Mail, Lock, Eye, EyeOff, ArrowLeft, Sparkles } from 'lucide-react';
import './Login.css';
import api from '../utils/api';
import LoadingOverlay from './common/LoadingOverlay';

const Login = ({ onSuccess }) => {
  const navigate = useNavigate();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [successMsg, setSuccessMsg] = useState('');

  // Forgot Password states
  const [isForgotPassword, setIsForgotPassword] = useState(false);
  const [forgotStep, setForgotStep] = useState(1); // 1: Request OTP, 2: Verify OTP
  const [otp, setOtp] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [showNewPassword, setShowNewPassword] = useState(false);
  const [showConfirmPassword, setShowConfirmPassword] = useState(false);

  // requirement: Remove token when login page loads
  React.useEffect(() => {
    localStorage.removeItem('session_token');
  }, []);

  const handleForgotRequest = async (e) => {
    e.preventDefault();
    setLoading(true);
    setError('');
    setSuccessMsg('');
    try {
      const response = await api.post(`/app/v1/forgot-password/request`, { email: email.trim() });
      const data = response.data;

      setSuccessMsg(data.message || 'OTP sent successfully.');
      setForgotStep(2);
    } catch (err) {
      if (err.response && err.response.data && err.response.data.detail) {
        setError(err.response.data.detail);
      } else {
        setError(err.message || 'Failed to request OTP');
      }
    } finally {
      setLoading(false);
    }
  };

  const handleForgotVerify = async (e) => {
    e.preventDefault();
    setLoading(true);
    setError('');
    setSuccessMsg('');
    try {
      const response = await api.post(`/app/v1/forgot-password/verify`, {
        email: email.trim(),
        otp: otp.trim(),
        new_password: newPassword,
        confirm_password: confirmPassword,
      });

      const data = response.data;
      setSuccessMsg(data.message || 'Password has been reset successfully.');
      setIsForgotPassword(false);
      setForgotStep(1);
      setOtp('');
      setNewPassword('');
      setConfirmPassword('');
      setPassword('');
      setError('');
    } catch (err) {
      if (err.response && err.response.data && err.response.data.detail) {
        setError(err.response.data.detail);
      } else {
        setError(err.message || 'Failed to reset password');
      }
    } finally {
      setLoading(false);
    }
  };

  const handleLogin = async (e) => {
    if (e) e.preventDefault();
    setLoading(true);
    setError('');
    setSuccessMsg('');

    try {
      const response = await api.post(`/app/v1/login`, { email: email.trim(), password: password.trim() });
      const data = response.data;

      if (data.access_token) {
        if (onSuccess) onSuccess(data.access_token);
        navigate('/dashboard?tab=dashboard&sub=followups', { replace: true });
      } else {
        throw new Error('Invalid credentials');
      }
    } catch (err) {
      let errMsg = 'Invalid credentials';
      if (err.response && err.response.data && err.response.data.detail) {
        errMsg = err.response.data.detail;
      }
      setError(errMsg);
      setPassword('');
      localStorage.removeItem('session_token');
    } finally {
      setLoading(false);
    }
  };

  const renderLoginForm = () => (
    <form className="form" onSubmit={handleLogin}>
      <div className="centerText">
        <h2>Welcome Back</h2>
        <p>Please enter your details to sign in.</p>
      </div>

      {error && <div className="auth-error-banner">{error}</div>}
      {successMsg && <div className="auth-success-banner">{successMsg}</div>}

      <div className="input-group">
        <span className="input-label" style={{ color: 'var(--text-primary)' }}>Email Address</span>
        <div className="input-wrapper">
          <div className="input-icon">
            <Mail size={18} />
          </div>
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="name@company.com"
            required
          />
        </div>
      </div>

      <div className="input-group">
        <span className="input-label" style={{ color: 'var(--text-primary)' }}>Password</span>
        <div className="input-wrapper">
          <div className="input-icon" style={{ zIndex: 10 }}>
            <Lock size={18} />
          </div>
          <input
            type={showPassword ? "text" : "password"}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="••••••••"
            required
          />
          <button
            type="button"
            className="password-toggle"
            onClick={() => setShowPassword(!showPassword)}
            aria-label={showPassword ? "Hide password" : "Show password"}
            style={{ zIndex: 10 }}
          >
            {showPassword ? <EyeOff size={18} /> : <Eye size={18} />}
          </button>
        </div>
      </div>

      <div style={{ textAlign: 'right' }}>
        <button
          type="button"
          className="forgot-password-link"
          onClick={() => { setIsForgotPassword(true); setForgotStep(1); setError(''); setSuccessMsg(''); setTimeout(() => setPassword(''), 0); }}
        >
          Forgot Password?
        </button>
      </div>

      <button type="submit" disabled={loading}>
        {loading ? 'Logging in...' : 'Sign In'}
      </button>
    </form>
  );

  const renderForgotRequestForm = () => (
    <form className="form" onSubmit={handleForgotRequest}>
      <div className="centerText">
        <h2>Forgot Password</h2>
        <p>Enter your email to receive an OTP.</p>
      </div>

      {error && <div className="auth-error-banner">{error}</div>}
      {successMsg && <div className="auth-success-banner">{successMsg}</div>}

      <div className="input-group">
        <span className="input-label" style={{ color: 'var(--text-primary)' }}>Email Address</span>
        <div className="input-wrapper">
          <div className="input-icon" style={{ zIndex: 10 }}>
            <Mail size={18} />
          </div>
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="name@company.com"
            required
          />
        </div>
      </div>

      <button type="submit" disabled={loading}>
        {loading ? 'Sending OTP...' : 'Send Reset OTP'}
      </button>

      <div className="forgot-footer">
        <button
          type="button"
          className="back-to-login"
          onClick={() => { setIsForgotPassword(false); setError(''); setSuccessMsg(''); }}
        >
          <ArrowLeft size={16} /> Back to Sign In
        </button>
      </div>
    </form>
  );

  const renderForgotVerifyForm = () => (
    <form className="form" onSubmit={handleForgotVerify}>
      <div className="centerText">
        <h2>Reset Password</h2>
        <p>Enter the OTP and your new password.</p>
      </div>

      {error && <div className="auth-error-banner">{error}</div>}
      {successMsg && <div className="auth-success-banner">{successMsg}</div>}

      <div className="input-group">
        <span className="input-label" style={{ color: 'var(--text-primary)' }}>Email Address</span>
        <div className="input-wrapper">
          <div className="input-icon" style={{ zIndex: 10 }}>
            <Mail size={18} />
          </div>
          <input
            type="email"
            value={email}
            disabled
          />
        </div>
      </div>

      <div className="input-group">
        <span className="input-label" style={{ color: 'var(--text-primary)' }}>OTP Code</span>
        <div className="input-wrapper">
          <div className="input-icon" style={{ zIndex: 10 }}>
            <Lock size={18} />
          </div>
          <input
            type="text"
            value={otp}
            onChange={(e) => setOtp(e.target.value)}
            placeholder="Enter 6-digit OTP"
            required
          />
        </div>
      </div>

      <div className="input-group">
        <span className="input-label" style={{ color: 'var(--text-primary)' }}>New Password</span>
        <div className="input-wrapper">
          <div className="input-icon" style={{ zIndex: 10 }}>
            <Lock size={18} />
          </div>
          <input
            type={showNewPassword ? "text" : "password"}
            value={newPassword}
            onChange={(e) => setNewPassword(e.target.value)}
            placeholder="New password"
            required
          />
          <button
            type="button"
            className="password-toggle"
            onClick={() => setShowNewPassword(!showNewPassword)}
            style={{ zIndex: 10 }}
          >
            {showNewPassword ? <EyeOff size={18} /> : <Eye size={18} />}
          </button>
        </div>
      </div>

      <div className="input-group">
        <span className="input-label" style={{ color: 'var(--text-primary)' }}>Confirm Password</span>
        <div className="input-wrapper">
          <div className="input-icon" style={{ zIndex: 10 }}>
            <Lock size={18} />
          </div>
          <input
            type={showConfirmPassword ? "text" : "password"}
            value={confirmPassword}
            onChange={(e) => setConfirmPassword(e.target.value)}
            placeholder="Confirm new password"
            required
          />
          <button
            type="button"
            className="password-toggle"
            onClick={() => setShowConfirmPassword(!showConfirmPassword)}
            style={{ zIndex: 10 }}
          >
            {showConfirmPassword ? <EyeOff size={18} /> : <Eye size={18} />}
          </button>
        </div>
      </div>

      <button type="submit" disabled={loading}>
        {loading ? 'Resetting...' : 'Reset Password'}
      </button>

      <div className="forgot-footer">
        <button
          type="button"
          className="back-to-login"
          onClick={() => { setIsForgotPassword(false); setForgotStep(1); setError(''); setSuccessMsg(''); }}
        >
          <ArrowLeft size={16} /> Back to Sign In
        </button>
      </div>
    </form>
  );

  return (
    <div className="login-page">
      <div className="bg-orb orb-1"></div>
      <div className="bg-orb orb-2"></div>
      {loading && <LoadingOverlay message={isForgotPassword ? "Processing Request..." : "Logging in..."} />}
      
      <div className="login-logo-external">
        Solve<span>Tax</span>
      </div>

      <div className={`login-container ${isForgotPassword && forgotStep === 2 ? 'reset-password-mode' : ''}`}>
        {!isForgotPassword
          ? renderLoginForm()
          : forgotStep === 1
            ? renderForgotRequestForm()
            : renderForgotVerifyForm()
        }
      </div>
    </div>
  );
};

export default Login;
