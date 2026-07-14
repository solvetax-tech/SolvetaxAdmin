/**
 * @file Homepage.jsx
 * @description Renders the public-facing landing page for the Slovetax platform.
 */
import React from 'react';
import { useNavigate } from 'react-router-dom';
import {
  ShieldCheck,
  Zap,
  BarChart3,
  CheckCircle2,
  ArrowRight,
  Clock,
  Globe,
  Users
} from 'lucide-react';
import './Homepage.css';
const Homepage = () => {
  const navigate = useNavigate();

  return (
    <div className="homepage-container">
      <header className="header">
        <div className="logo-section">
          <div className="logo-icon">S</div>
          <span className="logo-text">SolveTax</span>
        </div>
        <div className="header-buttons">
          <button className="btn-login" onClick={() => navigate('/login')}>Sign In</button>
          <button className="btn-start" onClick={() => navigate('/login')}>Get Started</button>
        </div>
      </header>

      <main className="main-content">
        {/* Hero Section */}
        <section className="hero-section">
          <div className="hero-content">
            <div className="eyebrow">Smart Tax Management</div>
            <h1>
              Tax Compliance<br />
              Made <span className="word-brand">Effortless</span>
            </h1>
            <p className="hero-description">
              Slovetax provides a comprehensive suite of tools for GST registration,
              automated tax filings, and enterprise-grade compliance tracking.
              Simplify your tax workflow today.
            </p>
            <div className="cta-row">
              <button className="btn-start hero-cta" onClick={() => navigate('/login')}>
                Start for Free <ArrowRight size={18} style={{ marginLeft: '8px' }} />
              </button>
            </div>
          </div>
        </section>

        {/* Features Section */}
        <section className="features-section">
          <div className="section-header">
            <h2>Why Choose Slovetax?</h2>
            <p>Powerful features designed for modern businesses and tax professionals.</p>
          </div>
          <div className="features-grid">
            <div className="feature-card">
              <div className="feature-icon"><Zap size={24} /></div>
              <h3>Automated Fillings</h3>
              <p>Reduce manual errors and save hundreds of hours with our automated GST filing engine.</p>
            </div>
            <div className="feature-card">
              <div className="feature-icon"><ShieldCheck size={24} /></div>
              <h3>Secure & Compliant</h3>
              <p>Built with enterprise-grade security to ensure your data is always safe and compliant.</p>
            </div>
            <div className="feature-card">
              <div className="feature-icon"><BarChart3 size={24} /></div>
              <h3>Real-time Analytics</h3>
              <p>Get deep insights into your tax liabilities and savings with our interactive dashboard.</p>
            </div>
          </div>
        </section>

        {/* Solutions Section */}
        <section className="solutions-section">
          <div className="solutions-container">
            <div className="solutions-content">
              <h2>Tailored Solutions for<br />Every Need</h2>
              <div className="solution-list">
                <div className="solution-item">
                  <CheckCircle2 className="check-icon" />
                  <div>
                    <h4>For Small Businesses</h4>
                    <p>Single-window GST registration and simplified monthly filings.</p>
                  </div>
                </div>
                <div className="solution-item">
                  <CheckCircle2 className="check-icon" />
                  <div>
                    <h4>For Tax Professionals</h4>
                    <p>Manage multiple clients from a unified dashboard with workflow automation.</p>
                  </div>
                </div>
                <div className="solution-item">
                  <CheckCircle2 className="check-icon" />
                  <div>
                    <h4>Enterprise Grade</h4>
                    <p>Custom integrations and dedicated account management for large corporations.</p>
                  </div>
                </div>
              </div>
            </div>
            <div className="solutions-image">
              <div style={{ textAlign: 'center' }}>
                <Globe size={120} color="var(--accent)" style={{ opacity: 0.2 }} />
                <p style={{ marginTop: '20px', color: 'var(--text-secondary)', fontWeight: 600 }}>Global Standards. Local Expertise.</p>
              </div>
            </div>
          </div>
        </section>
      </main>

      <footer className="footer">
        <div className="footer-grid">
          <div className="footer-col">
            <div className="logo-section" style={{ marginBottom: '20px' }}>
              <div className="logo-icon" style={{ background: 'var(--text-inverse)', color: 'var(--accent-deep)' }}>S</div>
              <span className="logo-text" style={{ color: 'var(--text-inverse)' }}>Slovetax</span>
            </div>
            <p style={{ color: 'rgba(255,255,255,0.6)', fontSize: '14px', lineHeight: '1.6' }}>
              Making tax management simple, smart, and accessible for everyone.
            </p>
          </div>
          <div className="footer-col">
            <h4>Product</h4>
            <ul>
              <li><a href="#features">Features</a></li>
              <li><a href="#solutions">Solutions</a></li>
              <li><a href="#pricing">Pricing</a></li>
            </ul>
          </div>
          <div className="footer-col">
            <h4>Company</h4>
            <ul>
              <li><a href="#about">About Us</a></li>
              <li><a href="#careers">Careers</a></li>
              <li><a href="#contact">Contact</a></li>
            </ul>
          </div>
          <div className="footer-col">
            <h4>Contact</h4>
            <p style={{ color: 'rgba(255,255,255,0.6)', fontSize: '14px' }}>
              support@slovetax.com<br />
              +1 (800) SLV-TAX
            </p>
          </div>
        </div>
        <div className="footer-bottom">
          <span>© 2026 Slovetax. All rights reserved.</span>
        </div>
      </footer>
    </div>
  );
};

export default Homepage;
