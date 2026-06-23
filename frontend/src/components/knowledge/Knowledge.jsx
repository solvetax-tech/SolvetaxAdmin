import React, { useState, useEffect } from 'react';
import { BookOpen, CreditCard, MapPin, FileCheck, Loader2, AlertCircle, TrendingUp, Briefcase } from 'lucide-react';
import api from '../../utils/api';
import { STAFF_SERVICE_CONFIG_PATH } from '../../utils/staffServiceConfigApi';
import './Knowledge.css';

const DEFAULT_SERVICE_CONFIGS = [
    { id: 1, service_category: 'GST', service_code: 'GST_REGISTRATION', service_name: 'GST Registration', description: 'New GST registration for businesses' },
    { id: 2, service_category: 'GST', service_code: 'GST_AMENDMENT', service_name: 'GST Amendment', description: 'Update GST registration details' },
    { id: 3, service_category: 'GST', service_code: 'GST_CANCELLATION', service_name: 'GST Cancellation', description: 'Cancel GST registration' },
    { id: 4, service_category: 'GST', service_code: 'GST_MONTHLY_FILING', service_name: 'GST Monthly Filing', description: 'Monthly GST return filing' },
    { id: 5, service_category: 'GST', service_code: 'GST_QUARTERLY_FILING', service_name: 'GST Quarterly Filing', description: 'Quarterly GST return filing' },
    { id: 6, service_category: 'GST', service_code: 'GST_ANNUAL_RETURN', service_name: 'GST Annual Return', description: 'GST annual return filing' },
    { id: 7, service_category: 'GST', service_code: 'GST_LUT', service_name: 'GST LUT Filing', description: 'Letter of Undertaking filing' },
    { id: 8, service_category: 'GST', service_code: 'GST_REFUND', service_name: 'GST Refund', description: 'GST refund claim' },
    { id: 9, service_category: 'GST', service_code: 'GST_NOTICE_REPLY', service_name: 'GST Notice Reply', description: 'Reply to GST notice' },
    { id: 10, service_category: 'INCOME_TAX', service_code: 'ITR_FILING', service_name: 'Income Tax Return Filing', description: 'Individual income tax return filing' },
    { id: 11, service_category: 'INCOME_TAX', service_code: 'ITR_NOTICE', service_name: 'ITR Notice Response', description: 'Response to income tax notice' },
    { id: 12, service_category: 'INCOME_TAX', service_code: 'ADVANCE_TAX', service_name: 'Advance Tax Calculation', description: 'Advance tax computation' },
    { id: 13, service_category: 'INCOME_TAX', service_code: 'CAPITAL_GAINS', service_name: 'Capital Gains Calculation', description: 'Capital gains tax calculation' },
    { id: 14, service_category: 'COMPANY', service_code: 'PVT_LTD_REG', service_name: 'Private Limited Registration', description: 'Private limited company incorporation' },
    { id: 15, service_category: 'COMPANY', service_code: 'LLP_REG', service_name: 'LLP Registration', description: 'Limited liability partnership registration' },
    { id: 16, service_category: 'COMPANY', service_code: 'OPC_REG', service_name: 'OPC Registration', description: 'One person company registration' },
    { id: 17, service_category: 'COMPANY', service_code: 'PARTNERSHIP_REG', service_name: 'Partnership Firm Registration', description: 'Partnership firm formation' },
    { id: 18, service_category: 'MCA', service_code: 'ROC_ANNUAL', service_name: 'ROC Annual Filing', description: 'Annual ROC compliance' },
    { id: 19, service_category: 'MCA', service_code: 'DIR3_KYC', service_name: 'DIR-3 KYC', description: 'Director KYC filing' },
    { id: 20, service_category: 'MCA', service_code: 'DIRECTOR_CHANGE', service_name: 'Director Change', description: 'Add or remove company director' },
    { id: 21, service_category: 'ACCOUNTING', service_code: 'MONTHLY_ACCOUNTING', service_name: 'Monthly Accounting', description: 'Monthly bookkeeping services' },
    { id: 22, service_category: 'ACCOUNTING', service_code: 'YEAR_END_FINALIZATION', service_name: 'Year End Finalization', description: 'Final accounts preparation' },
    { id: 23, service_category: 'PAYROLL', service_code: 'PAYROLL_PROCESSING', service_name: 'Payroll Processing', description: 'Employee salary processing' },
    { id: 24, service_category: 'PAYROLL', service_code: 'PF_FILING', service_name: 'PF Filing', description: 'Provident fund return filing' },
    { id: 25, service_category: 'PAYROLL', service_code: 'ESI_FILING', service_name: 'ESI Filing', description: 'ESI compliance filing' },
    { id: 26, service_category: 'TRADEMARK', service_code: 'TRADEMARK_REG', service_name: 'Trademark Registration', description: 'Trademark application filing' },
    { id: 27, service_category: 'TRADEMARK', service_code: 'TRADEMARK_RENEWAL', service_name: 'Trademark Renewal', description: 'Trademark renewal service' },
    { id: 28, service_category: 'LICENSE', service_code: 'MSME_REG', service_name: 'MSME Registration', description: 'Udyam MSME registration' },
    { id: 29, service_category: 'LICENSE', service_code: 'FSSAI_LICENSE', service_name: 'FSSAI License', description: 'Food license registration' },
    { id: 30, service_category: 'LICENSE', service_code: 'IEC_REG', service_name: 'Import Export Code', description: 'IEC registration' }
];

const Knowledge = () => {
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [pricing, setPricing] = useState([]);
    const [states, setStates] = useState([]);
    const [docTypes, setDocTypes] = useState([]);
    const [regTypes, setRegTypes] = useState([]);
    const [turnoverDetails, setTurnoverDetails] = useState([]);
    const [regStatuses, setRegStatuses] = useState([]);
    const [businessTypes, setBusinessTypes] = useState([]);
    const [documentConfigs, setDocumentConfigs] = useState({});
    const [designations, setDesignations] = useState({});
    const [serviceConfigs, setServiceConfigs] = useState([]);
    const [gstFilingConfigs, setGstFilingConfigs] = useState([]);
    const [gstFilingRuleEngine, setGstFilingRuleEngine] = useState([]);

    const fetchKnowledgeData = async () => {
        setLoading(true);
        setError(null);
        try {
            // Use allSettled for robustness against partial backend failures
            const results = await Promise.allSettled([
                api.get('/api/v1/payments_config/payment-config?entity_type=GST_REGISTRATION'),
                api.get('/api/v1/gst-registration/config/state'),
                api.get('/api/v1/gst-registration/config/document_type'),
                api.get('/api/v1/gst-registration/config/registration_type'),
                api.get('/api/v1/gst-registration/config/turnover_details'),
                api.get('/api/v1/gst-registration/config/registration_status'),
                api.get('/api/v1/gst-registration/config/business_type'),
                api.get('/api/v1/document-config/document-config-all'),
                api.get('/api/v1/gst-registrations/dynamic_filter?include_inactive=true&limit=100'),
                api.get(STAFF_SERVICE_CONFIG_PATH),
                api.get('/api/v1/gst-filing-config/gst-filing-config'),
                api.get('/api/v1/crm/filing-rule-engine/gst-filing-rule-all')
            ]);

            const [
                pricingRes,
                statesRes,
                docTypesRes,
                regTypesRes,
                turnoverRes,
                statusRes,
                businessRes,
                docConfigRes,
                gstRegistrationsRes,
                serviceConfigRes,
                gstFilingRes,
                gstFilingRuleRes
            ] = results;

            // Log results for debugging
            console.log("Knowledge Base API settle results:", results);

            // Mapping results to state
            if (pricingRes.status === 'fulfilled') setPricing(pricingRes.value.data?.data || []);
            if (statesRes.status === 'fulfilled') setStates(statesRes.value.data || []);
            if (docTypesRes.status === 'fulfilled') setDocTypes(docTypesRes.value.data || []);
            if (regTypesRes.status === 'fulfilled') setRegTypes(regTypesRes.value.data || []);
            if (turnoverRes.status === 'fulfilled') setTurnoverDetails(turnoverRes.value.data || []);
            if (statusRes.status === 'fulfilled') setRegStatuses(statusRes.value.data || []);
            if (businessRes.status === 'fulfilled') setBusinessTypes(businessRes.value.data || []);
            if (gstFilingRes.status === 'fulfilled') setGstFilingConfigs(gstFilingRes.value.data?.data || []);
            if (gstFilingRuleRes.status === 'fulfilled') setGstFilingRuleEngine(gstFilingRuleRes.value.data?.data || []);
            if (serviceConfigRes.status === 'fulfilled') {
                const serviceRows = serviceConfigRes.value.data?.data || serviceConfigRes.value.data || [];
                const dbRows = Array.isArray(serviceRows) ? serviceRows : [];
                const mergedByCode = new Map();
                DEFAULT_SERVICE_CONFIGS.forEach((row) => mergedByCode.set(row.service_code, row));
                dbRows.forEach((row, idx) => {
                    const code = row.service_code || `ROW_${row.id || idx}`;
                    mergedByCode.set(code, { ...mergedByCode.get(code), ...row });
                });
                const mergedRows = Array.from(mergedByCode.values()).sort((a, b) => {
                    const idA = Number(a.id || 0);
                    const idB = Number(b.id || 0);
                    if (idA !== idB) return idA - idB;
                    return String(a.service_code || '').localeCompare(String(b.service_code || ''));
                });
                setServiceConfigs(mergedRows);
            } else {
                setServiceConfigs([...DEFAULT_SERVICE_CONFIGS].sort((a, b) => Number(a.id || 0) - Number(b.id || 0)));
            }

            // Detailed Configs (Document Requirements)
            let configs = [];
            if (docConfigRes.status === 'fulfilled') {
                configs = docConfigRes.value.data?.data || [];
                const grouped = configs.reduce((acc, doc) => {
                    const cat = doc.ownership_category || 'GENERAL';
                    if (!acc[cat]) acc[cat] = [];
                    acc[cat].push(doc);
                    return acc;
                }, {});
                setDocumentConfigs(grouped);
            }

            const groupedDesignations = {};
            const designationSeen = new Set();

            if (gstRegistrationsRes.status === 'fulfilled') {
                const gstRows = gstRegistrationsRes.value.data?.data || [];
                const categoryToGstId = {};
                gstRows.forEach((row) => {
                    const category = (row.ownership_category || '').trim().toUpperCase();
                    if (!category) return;
                    if (!categoryToGstId[category]) {
                        categoryToGstId[category] = row.id;
                    }
                });

                const designationReqs = Object.entries(categoryToGstId).map(([category, gstId]) =>
                    api.get(`/api/v1/gst-people/gst-registration/${gstId}/designations`)
                        .then((res) => ({ status: 'fulfilled', category, data: res.data?.designations || [] }))
                        .catch(() => ({ status: 'rejected', category, data: [] }))
                );

                const designationResults = await Promise.all(designationReqs);
                designationResults.forEach((result) => {
                    if (result.status !== 'fulfilled') return;
                    const category = result.category;
                    result.data.forEach((row) => {
                        const name = (row.display_name || row.value || '').trim();
                        if (!name) return;
                        const key = `${category}::${name.toUpperCase()}`;
                        if (designationSeen.has(key)) return;
                        designationSeen.add(key);
                        if (!groupedDesignations[category]) groupedDesignations[category] = [];
                        groupedDesignations[category].push({
                            display_name: name,
                            description: row.description || row.value || name
                        });
                    });
                });
            }

            if (Object.keys(groupedDesignations).length === 0 && configs.length > 0) {
                const fallback = configs.filter((row) => String(row.config_type || '').toUpperCase() === 'DESIGNATION');
                fallback.forEach((row) => {
                    const category = (row.ownership_category || 'GENERAL').trim().toUpperCase();
                    if (!groupedDesignations[category]) groupedDesignations[category] = [];
                    groupedDesignations[category].push({
                        display_name: row.display_name || row.value || 'Designation',
                        description: row.description || row.value || '-'
                    });
                });
            }

            setDesignations(groupedDesignations);

            // Fallback for docTypes if specific endpoint is empty but master config has data
            if ((!docTypesRes.value?.data || docTypesRes.value.data.length === 0) && configs.length > 0) {
                const uniqueTypes = Array.from(new Set(configs.map(d => d.display_name)))
                    .map(name => ({ display_name: name }));
                setDocTypes(uniqueTypes);
            }

            // Error check: If most failed, show general error
            const failureCount = results.filter(r => r.status === 'rejected').length;
            if (failureCount > results.length - 2) {
                throw new Error("Unable to sync reference data. Please check your connection.");
            }

        } catch (err) {
            console.error("Error fetching knowledge data:", err);
            setError("Failed to synchronize knowledge base.");
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        fetchKnowledgeData();
    }, []);

    if (loading) {
        return (
            <div className="knowledge-loading">
                <Loader2 className="spinner" size={40} />
                <p>Loading System Intelligence...</p>
            </div>
        );
    }

    if (error) {
        return (
            <div className="knowledge-error">
                <AlertCircle size={40} />
                <p>{error}</p>
                <button onClick={fetchKnowledgeData} className="btn-retry">Retry</button>
            </div>
        );
    }

    return (
        <div className="knowledge-container">
            <div className="knowledge-header">
                <div className="header-icon">
                    <BookOpen size={24} />
                </div>
                <div className="header-text">
                    <h1>System Knowledge Base</h1>
                    <p>Reference guide for pricing, standards, and system configurations.</p>
                </div>
            </div>

            <div className="knowledge-grid">
                {/* Pricing Section */}
                <section className="knowledge-section pricing-card">
                    <div className="section-header">
                        <CreditCard size={20} />
                        <h2>GST Registration Pricing</h2>
                    </div>
                    <div className="table-wrapper">
                        <table className="knowledge-table services-table">
                            <thead>
                                <tr>
                                    <th>Ownership Component</th>
                                    <th>Base Amount</th>
                                    <th>Description</th>
                                </tr>
                            </thead>
                            <tbody>
                                {pricing.length > 0 ? pricing.map((p, idx) => (
                                    <tr key={idx}>
                                        <td>{p.display_name}</td>
                                        <td className="price-value">₹{p.amount}</td>
                                        <td>{p.description || '-'}</td>
                                    </tr>
                                )) : (
                                    <tr>
                                        <td colSpan="3" className="no-data-msg">No pricing information available.</td>
                                    </tr>
                                )}
                            </tbody>
                        </table>
                    </div>
                </section>

                {/* Income Tax Pricing Section */}
                <section className="knowledge-section pricing-card">
                    <div className="section-header">
                        <CreditCard size={20} style={{ color: '#3b82f6' }} />
                        <h2>Income Tax Filing Pricing</h2>
                    </div>
                    <div className="table-wrapper">
                        <table className="knowledge-table services-table">
                            <thead>
                                <tr>
                                    <th>Filing Category</th>
                                    <th>Amount</th>
                                    <th>Service Details</th>
                                </tr>
                            </thead>
                            <tbody>
                                <tr><td>ITR - Salary (Null)</td><td className="price-value">₹599</td><td>Salary return with null values</td></tr>
                                <tr><td>ITR - Salary</td><td className="price-value">₹999</td><td>Standard salary return</td></tr>
                                <tr><td>ITR - Business</td><td className="price-value">₹1,599</td><td>Business income (ITR-3)</td></tr>
                                <tr><td>ITR - Profession</td><td className="price-value">₹1,499</td><td>Profession income (ITR-3/4)</td></tr>
                                <tr><td>ITR - House Property</td><td className="price-value">₹999</td><td>House property income (ITR-1/2)</td></tr>
                                <tr><td>ITR - Capital Gains</td><td className="price-value">₹1,999</td><td>Capital gains (ITR-2/3)</td></tr>
                                <tr><td>ITR - Other Sources</td><td className="price-value">₹899</td><td>Other income sources</td></tr>
                                <tr><td>ITR - Multiple Sources</td><td className="price-value">₹2,299</td><td>Mix of income sources</td></tr>
                                <tr><td>ITR Notice Response</td><td className="price-value">₹999</td><td>Response to scrutiny notices</td></tr>
                                <tr><td>Advance Tax</td><td className="price-value">₹799</td><td>Computation & payment</td></tr>
                                <tr><td>Capital Gains Calc</td><td className="price-value">₹1,999</td><td>Standalone computation</td></tr>
                            </tbody>
                        </table>
                    </div>
                </section>

                {/* States Section */}
                <section className="knowledge-section states-card">
                    <div className="section-header">
                        <MapPin size={20} />
                        <h2>Standardized States</h2>
                    </div>
                    <div className="list-wrapper">
                        <div className="state-tags">
                            {states.length > 0 ? states.map((s, idx) => (
                                <div key={idx} className="state-tag">
                                    <span className="state-code">{s.value}</span>
                                    <span className="state-name">{s.display_name}</span>
                                </div>
                            )) : (
                                <p className="no-data-msg">No state information available.</p>
                            )}
                        </div>
                    </div>
                </section>

                {/* Registration Types Section */}
                <section className="knowledge-section reg-types-card">
                    <div className="section-header">
                        <TrendingUp size={20} />
                        <h2>Registration Types</h2>
                    </div>
                    <div className="list-wrapper">
                        <ul className="doc-list">
                            {regTypes.length > 0 ? regTypes.map((t, idx) => (
                                <li key={idx} className="doc-item">
                                    <span className="dot" />
                                    <span>{t.display_name}</span>
                                </li>
                            )) : (
                                <p className="no-data-msg">No registration types available.</p>
                            )}
                        </ul>
                    </div>
                </section>

                {/* Document Types Section */}
                <section className="knowledge-section docs-card">
                    <div className="section-header">
                        <FileCheck size={20} />
                        <h2>Accepted Document Types</h2>
                    </div>
                    <div className="list-wrapper">
                        <ul className="doc-list">
                            {docTypes.length > 0 ? docTypes.map((d, idx) => (
                                <li key={idx} className="doc-item">
                                    <FileCheck size={14} className="doc-icon" />
                                    <span>{d.display_name}</span>
                                </li>
                            )) : (
                                <p className="no-data-msg">No document type information available.</p>
                            )}
                        </ul>
                    </div>
                </section>

                <section className="knowledge-section designation-card">
                    <div className="section-header">
                        <FileCheck size={20} />
                        <h2>Designation Reference</h2>
                    </div>
                    <div className="list-wrapper">
                        <ul className="doc-list">
                            {Object.keys(designations).length > 0 ? Object.entries(designations).map(([category, list]) => (
                                <li key={category} className="doc-item designation-group-item">
                                    <div className="designation-group-title">{category.replace(/_/g, ' ')}</div>
                                    <div className="designation-group-values">
                                        {list.map((d, idx) => (
                                            <span key={`${category}-${idx}`} className="designation-chip">
                                                {d.display_name}
                                            </span>
                                        ))}
                                    </div>
                                </li>
                            )) : (
                                <p className="no-data-msg">No designation information configured.</p>
                            )}
                        </ul>
                    </div>
                </section>

                {/* Business Types Section */}
                <section className="knowledge-section business-card">
                    <div className="section-header">
                        <div style={{ color: '#ec4899' }}><FileCheck size={20} /></div>
                        <h2>Business Categories</h2>
                    </div>
                    <div className="list-wrapper">
                        <div className="state-tags">
                            {businessTypes.length > 0 ? businessTypes.map((b, idx) => (
                                <div key={idx} className="state-tag" style={{ borderLeft: '3px solid #ec4899' }}>
                                    <span className="state-name">{b.display_name}</span>
                                </div>
                            )) : (
                                <p className="no-data-msg">No business categories available.</p>
                            )}
                        </div>
                    </div>
                </section>

                {/* Turnover Details Section */}
                <section className="knowledge-section turnover-card">
                    <div className="section-header">
                        <TrendingUp size={20} />
                        <h2>Turnover Brackets</h2>
                    </div>
                    <div className="list-wrapper">
                        <ul className="doc-list">
                            {turnoverDetails.length > 0 ? turnoverDetails.map((t, idx) => (
                                <li key={idx} className="doc-item">
                                    <span className="dot" style={{ backgroundColor: '#2eb87a' }} />
                                    <span>{t.display_name}</span>
                                </li>
                            )) : (
                                <p className="no-data-msg">No turnover details available.</p>
                            )}
                        </ul>
                    </div>
                </section>

                {/* Registration Statuses Section */}
                <section className="knowledge-section status-card">
                    <div className="section-header">
                        <FileCheck size={20} />
                        <h2>System Statuses</h2>
                    </div>
                    <div className="list-wrapper">
                        <div className="state-tags">
                            {regStatuses.length > 0 ? regStatuses.map((s, idx) => (
                                <div key={idx} className="state-tag" style={{ borderLeft: '3px solid #f59e0b' }}>
                                    <span className="state-name">{s.display_name}</span>
                                </div>
                            )) : (
                                <p className="no-data-msg">No statuses available.</p>
                            )}
                        </div>
                    </div>
                </section>

                {/* GST Filing Config Section */}
                <section className="knowledge-section filing-config-card full-width-section">
                    <div className="section-header">
                        <div style={{ color: '#8b5cf6' }}><FileCheck size={20} /></div>
                        <h2>GST Filing Configurations</h2>
                    </div>
                    <div className="table-wrapper">
                        <table className="knowledge-table filing-table">
                            <thead>
                                <tr>
                                    <th>Filing Type</th>
                                    <th>Display Name</th>
                                    <th>Description</th>
                                    <th>Category</th>
                                    <th>Status</th>
                                </tr>
                            </thead>
                            <tbody>
                                {gstFilingConfigs.length > 0 ? gstFilingConfigs.map((f, idx) => (
                                    <tr key={idx}>
                                        <td style={{ fontWeight: '600', color: 'var(--text-primary)' }}>{f.filing_type}</td>
                                        <td>{f.display_name || f.filing_type}</td>
                                        <td style={{ fontSize: '13px', color: 'var(--text-primary)', lineHeight: '1.4' }}>{f.description || '-'}</td>
                                        <td>{f.filing_category}</td>
                                        <td>
                                            <span style={{
                                                fontSize: '11px',
                                                padding: '4px 8px',
                                                borderRadius: '6px',
                                                background: f.is_active ? 'rgba(16, 185, 129, 0.1)' : 'rgba(239, 68, 68, 0.1)',
                                                color: f.is_active ? '#2eb87a' : '#ef4444',
                                                border: `1px solid ${f.is_active ? 'rgba(16, 185, 129, 0.2)' : 'rgba(239, 68, 68, 0.2)'}`,
                                                fontWeight: '700',
                                                textTransform: 'uppercase'
                                            }}>
                                                {f.is_active ? 'Active' : 'Inactive'}
                                            </span>
                                        </td>
                                    </tr>
                                )) : (
                                    <tr>
                                        <td colSpan="5" className="no-data-msg">No filing configurations available.</td>
                                    </tr>
                                )}
                            </tbody>
                        </table>
                    </div>
                </section>

                {/* Customer Services Section */}
                <section className="knowledge-section services-card full-width-section">
                    <div className="section-header">
                        <Briefcase size={20} />
                        <h2>Customer Services Reference</h2>
                    </div>
                    <div className="table-wrapper">
                        <table className="knowledge-table">
                            <thead>
                                <tr>
                                    <th>ID</th>
                                    <th>Category</th>
                                    <th>Service Code</th>
                                    <th>Service Name</th>
                                    <th>Description</th>
                                </tr>
                            </thead>
                            <tbody>
                                {serviceConfigs.length > 0 ? serviceConfigs.map((service, idx) => (
                                    <tr key={`${service.id || idx}-${service.service_code || 'svc'}`}>
                                        <td>{service.id ?? '-'}</td>
                                        <td>{service.service_category || '-'}</td>
                                        <td>{service.service_code || '-'}</td>
                                        <td>{service.service_name || '-'}</td>
                                        <td>{service.description || '-'}</td>
                                    </tr>
                                )) : (
                                    <tr>
                                        <td colSpan="5" className="no-data-msg">No service configuration available.</td>
                                    </tr>
                                )}
                            </tbody>
                        </table>
                    </div>
                </section>

                {/* Document Requirements (from document_config.py) */}
                <section className="knowledge-section config-card full-width-section">
                    <div className="section-header">
                        <FileCheck size={20} />
                        <h2>Document Requirements by Entity Type</h2>
                    </div>
                    <div className="config-grid">
                        {Object.keys(documentConfigs).length > 0 ? Object.entries(documentConfigs).map(([category, docs], idx) => (
                            <div key={idx} className="config-category-group">
                                <h3>{category.replace(/_/g, ' ')}</h3>
                                <ul className="config-doc-list">
                                    {docs.map((doc, dIdx) => (
                                        <li key={dIdx} className={doc.is_mandatory ? 'mandatory' : 'optional'}>
                                            <span className="doc-bullet">•</span>
                                            <span className="doc-name">{doc.display_name}</span>
                                            {doc.is_mandatory && <span className="mandatory-tag">Required</span>}
                                        </li>
                                    ))}
                                </ul>
                            </div>
                        )) : (
                            <p className="no-data-msg">No entity-specific document requirements found.</p>
                        )}
                    </div>
                </section>

                {/* GST Filing Standard Rules (from gst_filing_rule_engine.py) */}
                <section className="knowledge-section filing-rule-card full-width-section">
                    <div className="section-header">
                        <div style={{ color: '#2eb87a' }}><FileCheck size={20} /></div>
                        <h2>GST Filing Standard Rules</h2>
                    </div>
                    <div className="table-wrapper">
                        <table className="knowledge-table filing-table">
                            <thead>
                                <tr>
                                    <th>Filing Type</th>
                                    <th>Display Name</th>
                                    <th>Return Type</th>
                                    <th>Category</th>
                                    <th>Frequency</th>
                                    <th>Taxpayer Type</th>
                                    <th>Due Day</th>
                                    <th>Secondary Day</th>
                                    <th>Offset</th>
                                    <th>Turnover Limit</th>
                                    <th>Status</th>
                                </tr>
                            </thead>
                            <tbody>
                                {gstFilingRuleEngine.length > 0 ? gstFilingRuleEngine.map((r, idx) => (
                                    <tr key={idx} style={{ fontSize: '13px' }}>
                                        <td style={{ fontWeight: '600', color: 'var(--text-primary)' }}>{r.filing_type}</td>
                                        <td>{r.display_name || '-'}</td>
                                        <td>{r.return_type || '-'}</td>
                                        <td>{r.filing_category || '-'}</td>
                                        <td>{r.frequency || '-'}</td>
                                        <td>{r.taxpayer_type || '-'}</td>
                                        <td>{r.due_day ?? '-'}</td>
                                        <td>{r.due_day_secondary ?? '-'}</td>
                                        <td>{r.due_month_offset ?? '-'}</td>
                                        <td>{r.turnover_limits || '-'}</td>
                                        <td>
                                            <span style={{
                                                fontSize: '11px',
                                                padding: '4px 8px',
                                                borderRadius: '6px',
                                                background: r.is_active ? 'rgba(16, 185, 129, 0.1)' : 'rgba(239, 68, 68, 0.1)',
                                                color: r.is_active ? '#2eb87a' : '#ef4444',
                                                border: `1px solid ${r.is_active ? 'rgba(16, 185, 129, 0.2)' : 'rgba(239, 68, 68, 0.2)'}`,
                                                fontWeight: '700',
                                                textTransform: 'uppercase'
                                            }}>
                                                {r.is_active ? 'Active' : 'Inactive'}
                                            </span>
                                        </td>
                                    </tr>
                                )) : (
                                    <tr>
                                        <td colSpan="11" className="no-data-msg">No filing rules available.</td>
                                    </tr>
                                )}
                            </tbody>
                        </table>
                    </div>
                </section>
            </div>
        </div>
    );
};

export default Knowledge;
