import React, { useState, useEffect } from 'react';
import {
    X,
    CheckCircle2,
    IndianRupee,
    Tag,
    Wallet,
    MessageSquare,
    Loader2,
    ArrowRight,
    AlertCircle,
    FileText,
    Shield
} from 'lucide-react';
import api from '../../utils/api';
import { getCustomerServiceById } from '../../utils/customerServiceApi';
import { getGstFilingReturnDetailById } from '../../utils/gstFilingReturnApi';
import './AddPayment.css';
import '../employees/AddEmployeeModal.css';
import FormCustomSelect from '../common/FormCustomSelect';
import { optionsFromConfigOnly } from '../common/selectOptionUtils';

const SERVICE_TYPES = ['GST_REGISTRATION', 'GST_FILING', 'GST_FILING_RETURN_DETAILS', 'INCOME_TAX', 'CUSTOMER_SERVICE'];

/** Legacy deep-links used singular GST_FILING_RETURN_DETAIL. */
const normalizeServiceType = (value) => (
    value === 'GST_FILING_RETURN_DETAIL' ? 'GST_FILING_RETURN_DETAILS' : value
);

const cleanDisplayLabel = (value) => {
    if (value == null) return '';
    const s = String(value).trim();
    if (!s || s.toLowerCase() === 'n/a' || s === 'string') return '';
    return s;
};

const buildPaymentTargetLabel = (targetCode, customerName, businessName, entityId) => {
    const code = cleanDisplayLabel(targetCode);
    const person = cleanDisplayLabel(customerName);
    const biz = cleanDisplayLabel(businessName);

    const segments = code ? [code] : [`ID: ${entityId}`];
    const nameParts = [];
    if (person) nameParts.push(person);
    if (biz && (!person || biz.toLowerCase() !== person.toLowerCase())) {
        nameParts.push(biz);
    }
    if (nameParts.length) {
        segments.push(nameParts.join(' – '));
    }
    return segments.join(' – ');
};

const AddPayment = ({ onBack, isAdmin, initialEntityId, initialServiceType }) => {
    const [step, setStep] = useState(1);
    const [serviceType, setServiceType] = useState(
        SERVICE_TYPES.includes(initialServiceType) ? initialServiceType : 'GST_REGISTRATION'
    );

    // Step 1 State
    const [entityIdInput, setEntityIdInput] = useState(initialEntityId || '');
    const [generating, setGenerating] = useState(false);

    useEffect(() => {
        const normalized = normalizeServiceType(initialServiceType);
        if (SERVICE_TYPES.includes(normalized)) {
            setServiceType(normalized);
        }
    }, [initialServiceType]);

    // Auto-load payment form when opened with entity_id + service_type (e.g. from dashboard)
    useEffect(() => {
        const normalized = normalizeServiceType(initialServiceType);
        if (!initialEntityId || !SERVICE_TYPES.includes(normalized)) return;
        setEntityIdInput(String(initialEntityId));
        setServiceType(normalized);
        handleGeneratePayment({ preventDefault: () => {} });
        // eslint-disable-next-line react-hooks/exhaustive-deps -- run once when deep-link params are set
    }, [initialEntityId, initialServiceType]);

    // Step 2 State
    const [backendData, setBackendData] = useState(null);
    const [formData, setFormData] = useState({
        original_amount: '',
        discount: 0,
        paid_amount: 0,
        remarks: ''
    });

    const [submitting, setSubmitting] = useState(false);
    const [error, setError] = useState(null);
    const [success, setSuccess] = useState(false);
    const [paymentStatus, setPaymentStatus] = useState(null); // To store success message type
    const [isFormDisabled, setIsFormDisabled] = useState(false);

    // Helper to extract user-friendly error message from structured backend responses
    const getErrorMessage = (err, fallback = "An unexpected error occurred.") => {
        const detail = err.response?.data?.detail;
        if (typeof detail === 'string') return detail;
        if (detail?.error?.message) return detail.error.message;
        if (detail?.message) return detail.message;
        if (Array.isArray(detail)) {
            return detail.map(d => d.msg).join(', ') || fallback;
        }
        return err.response?.data?.error || err.message || fallback;
    };

    // Handle Step 1 (Generate Payment)
    const handleGeneratePayment = async (e) => {
        if (e) e.preventDefault();
        if (!entityIdInput) return;

        setGenerating(true);
        setError(null);

        try {
            // Fetch Payment Config with entity_type
            let backendInfo = { amount: 0, remaining_amount: 0, original_amount: 0 };
            let resData = {};
            try {
                const configRes = await api.get(`/api/v1/payments_config/amount/${entityIdInput}?entity_type=${serviceType}`);
                resData = configRes.data?.data || configRes.data || {};
                const original = parseFloat(resData.original_amount ?? resData.amount ?? 0) || 0;
                const totalDiscount = parseFloat(resData.total_discount ?? 0) || 0;
                const totalPaid = parseFloat(resData.total_paid ?? 0) || 0;
                const netAmount = parseFloat(resData.net_amount ?? (original - totalDiscount)) || 0;
                const remaining =
                    parseFloat(resData.remaining_amount ?? resData.payable_amount ?? (netAmount - totalPaid)) || 0;
                backendInfo = {
                    amount: original,
                    original_amount: original,
                    total_discount: totalDiscount,
                    total_paid: totalPaid,
                    net_amount: netAmount,
                    remaining_amount: remaining,
                    payable_amount: remaining,
                };
            } catch (configErr) {
                if (serviceType !== 'INCOME_TAX' && serviceType !== 'GST_FILING') {
                    console.error("Config fetch failed:", configErr);
                    throw configErr;
                }
                console.warn(`Using ${serviceType} payment fallback - backend config missing.`);
                backendInfo = {
                    amount: 0,
                    remaining_amount: serviceType === 'INCOME_TAX' ? 999999 : 0,
                    original_amount: 0,
                    total_discount: 0,
                    total_paid: 0,
                    net_amount: 0,
                    payable_amount: 0,
                };
            }

            let targetCode = resData.target_code || resData.ownership_category || '';
            let customerName = resData.customer_name || '';
            let businessName = resData.business_name || '';
            let targetLabel = resData.target_label || '';

            // Fallback entity lookup when payments_config did not return target_label (older cache / edge cases)
            if (!targetLabel) {
                try {
                    if (serviceType === 'GST_REGISTRATION') {
                        const gstRes = await api.get(`/api/v1/gst-registrations/dynamic_filter?gst_registration_id=${entityIdInput}&include_inactive=true&limit=1`);
                        const item = gstRes.data?.data?.[0];
                        if (item) {
                            targetCode = item.gstin || item.gst_number || '';
                            customerName = item.client_name || item.full_name || '';
                            businessName = item.business_name || item.legal_name || '';
                        }
                    } else if (serviceType === 'GST_FILING') {
                        const filingRes = await api.get(`/api/v1/gst-filings/filter?id=${entityIdInput}&include_inactive=true&limit=1`);
                        const item = filingRes.data?.data?.[0];
                        if (item) {
                            targetCode = item.gstin || '';
                            customerName = item.client_name || item.customer_name || item.full_name || '';
                            businessName = item.business_name || '';
                        }
                    } else if (serviceType === 'INCOME_TAX') {
                        const itRes = await api.get(`/api/v1/income-tax/${entityIdInput}`);
                        const item = itRes.data?.data || itRes.data;
                        if (item) {
                            targetCode = item.pan_number || '';
                            customerName = item.client_name || '';
                            businessName = item.business_name || '';

                            // If we are in fallback mode (amount is 0 or 999999), suggest based on source_of_income
                            if (backendInfo.amount === 0 || backendInfo.remaining_amount === 999999) {
                                const ITR_PRICING = {
                                    SALARY: 999,
                                    BUSINESS: 1599,
                                    PROFESSION: 1499,
                                    HOUSE_PROPERTY: 999,
                                    CAPITAL_GAINS: 1999,
                                    OTHER_SOURCES: 899,
                                    MULTIPLE_SOURCES: 2299,
                                    DEFAULT: 699,
                                };
                                const sources = Array.isArray(item.source_of_income)
                                    ? item.source_of_income
                                    : item.source_of_income
                                      ? [item.source_of_income]
                                      : [];
                                const suggestedAmount = sources.length > 1
                                    ? ITR_PRICING.MULTIPLE_SOURCES
                                    : (ITR_PRICING[sources[0]] || ITR_PRICING.DEFAULT);
                                backendInfo.amount = suggestedAmount;
                                backendInfo.remaining_amount = suggestedAmount;
                                backendInfo.original_amount = suggestedAmount;
                            }
                        }
                    } else if (serviceType === 'CUSTOMER_SERVICE') {
                        const csRes = await getCustomerServiceById(entityIdInput);
                        const item = csRes?.data || csRes;
                        if (item) {
                            targetCode = item.service_code || item.service_name || '';
                            customerName = item.full_name || '';
                            businessName = item.business_name || '';
                        }
                    } else if (serviceType === 'GST_FILING_RETURN_DETAILS') {
                        const item = await getGstFilingReturnDetailById(entityIdInput);
                        if (item) {
                            targetCode = item.gstin || '';
                            customerName = item.client_name || item.customer_name || item.full_name || '';
                            const period = item.filing_period || item.return_cycle || '';
                            businessName = item.business_name
                                ? (period ? `${item.business_name} (${period})` : item.business_name)
                                : period;
                        }
                    }
                    targetLabel = buildPaymentTargetLabel(
                        targetCode,
                        customerName,
                        businessName,
                        entityIdInput,
                    );
                } catch (err) {
                    console.error('Failed silently to fetch entity details', err);
                }
            }

            if (!targetLabel) {
                targetLabel = buildPaymentTargetLabel(targetCode, customerName, businessName, entityIdInput);
            }

            setBackendData({
                ...backendInfo,
                entity_id: entityIdInput,
                entity_type: serviceType,
                target_code: targetCode,
                customer_name: customerName,
                business_name: businessName,
                target_label: targetLabel,
                gstin: targetCode || 'N/A',
                total_discount: backendInfo.total_discount ?? 0,
                total_paid: backendInfo.total_paid ?? 0,
            });
            
            // New discount / paid are THIS installment only (backend sums prior rows).
            const dueNow = backendInfo.remaining_amount ?? backendInfo.payable_amount ?? 0;
            const isEditableOriginalFirst =
                (serviceType === 'GST_FILING' || serviceType === 'GST_FILING_RETURN_DETAILS')
                && (parseFloat(backendInfo.total_paid) || 0) === 0
                && (parseFloat(backendInfo.total_discount) || 0) === 0;
            setFormData({
                original_amount: isEditableOriginalFirst
                    ? (dueNow > 0 ? String(dueNow) : (backendInfo.original_amount > 0 ? String(backendInfo.original_amount) : ''))
                    : '',
                discount: 0,
                paid_amount: !isEditableOriginalFirst && dueNow > 0 ? dueNow : '',
                remarks: ''
            });

            setStep(2);
        } catch (err) {
            const status = err.response?.status;
            if (status === 404) {
                const entityLabel =
                    serviceType === 'GST_FILING'
                        ? 'Filing'
                        : serviceType === 'GST_FILING_RETURN_DETAILS'
                          ? 'GST filing return detail'
                          : serviceType === 'INCOME_TAX'
                            ? 'Income Tax record'
                            : serviceType === 'CUSTOMER_SERVICE'
                              ? 'Customer service'
                              : 'Registration';
                setError(`${entityLabel} not found for ID: ${entityIdInput}.`);
            } else if (status === 409) {
                setError(getErrorMessage(err, "Payment already completed for this service."));
            } else {
                console.error("Failed to generate payment:", err);
                setError(getErrorMessage(err, "Failed to fetch payment configuration."));
            }
        } finally {
            setGenerating(false);
        }
    };

    // Handle Step 2 inputs
    const handleChange = (e) => {
        const { name, value } = e.target;
        setFormData(prev => ({ ...prev, [name]: value }));
    };

    // Handle final submission
    const handleSubmit = async (e) => {
        if (e) e.preventDefault();
        setError(null);
        setSuccess(false);

        if (!backendData || !backendData.entity_id) {
            setError("Invalid payment details.");
            return;
        }

        setSubmitting(true);
        try {
            // Dynamic endpoint based on serviceType
            const endpoint =
                serviceType === 'GST_FILING'
                    ? '/api/v1/filing-payments'
                    : serviceType === 'GST_FILING_RETURN_DETAILS'
                      ? '/api/v1/gst-filing-return-details-payments'
                    : serviceType === 'INCOME_TAX'
                      ? '/api/v1/income-tax-payments'
                      : serviceType === 'CUSTOMER_SERVICE'
                        ? '/api/v1/customer-service-payments'
                        : '/api/v1/payments';
            
            const submitOriginal = canEditOriginalAmount
                ? parseFloat(formData.original_amount) || 0
                : parseFloat(backendData.original_amount) || 0;

            const response = await api.post(endpoint, {
                entity_id: backendData.entity_id,
                amount: submitOriginal,
                discount: parseFloat(formData.discount) || 0,
                paid_amount: parseFloat(formData.paid_amount) || 0,
                remarks: formData.remarks
            });
            
            const status = response.data.payment_status;
            setPaymentStatus(status);
            setSuccess(true);
            setIsFormDisabled(true);
            window.dispatchEvent(new Event('st_payments_updated'));

            setTimeout(() => onBack(), 3000);
        } catch (err) {
            console.error("Payment creation failed:", err);
            const status = err.response?.status;
            if (status === 409) {
                setError("Payment already completed");
                setIsFormDisabled(true);
            } else if (status === 404) {
                setError("Entity not found");
            } else {
                setError(getErrorMessage(err, "Failed to create payment."));
            }
        } finally {
            setSubmitting(false);
        }
    };

    // UI Calculation & Validation
    const canEditOriginalAmount = Boolean(
        backendData
        && (backendData.entity_type === 'GST_FILING'
            || backendData.entity_type === 'GST_FILING_RETURN_DETAILS')
        && (parseFloat(backendData.total_paid) || 0) === 0
        && (parseFloat(backendData.total_discount) || 0) === 0,
    );

    const effectiveOriginal = canEditOriginalAmount
        ? parseFloat(formData.original_amount) || 0
        : (backendData ? parseFloat(backendData.original_amount) || 0 : 0);

    const totalDiscountPrior = backendData ? parseFloat(backendData.total_discount) || 0 : 0;
    const totalPaidPrior = backendData ? parseFloat(backendData.total_paid) || 0 : 0;

    const discount = parseFloat(formData.discount) || 0;
    const paidAmount = parseFloat(formData.paid_amount) || 0;
    const remaining_amount = Math.max(
        0,
        effectiveOriginal - totalDiscountPrior - totalPaidPrior,
    );
    const payable = Math.max(0, remaining_amount - discount);

    const hasInstallment = discount > 0 || paidAmount > 0;
    const isInvalid =
        !backendData ||
        (canEditOriginalAmount && effectiveOriginal <= 0) ||
        discount < 0 ||
        discount > remaining_amount ||
        paidAmount < 0 ||
        paidAmount > remaining_amount ||
        paidAmount > payable ||
        !hasInstallment;

    return (
        <div className="premium-filter-overlay show" onClick={onBack}>
            <div className={`premium-edit-modal-v4 add-payment-content ${step === 1 ? 'step-1-modal' : ''}`} onClick={e => e.stopPropagation()}>
                <button className="btn-close-modal-v4" onClick={onBack} aria-label="Close" style={{ position: 'absolute', top: '24px', right: '24px', zIndex: 10 }}>
                    <X size={20} />
                </button>

                {success ? (
                    <div className="modal-success-state" style={{ padding: '60px 40px', textAlign: 'center' }}>
                        <div className="success-icon-wrapper" style={{ marginBottom: '24px' }}>
                            <CheckCircle2 size={64} className="success-tick" color="#2eb87a" />
                        </div>
                        <h2 style={{ fontSize: '28px', color: 'var(--text-primary)', marginBottom: '12px' }}>
                            {paymentStatus === "PAID" ? "Payment Completed!" : "Payment Recorded"}
                        </h2>
                        <p style={{ color: 'var(--text-muted)' }}>
                            {paymentStatus === "PAID" 
                                ? "The payment has been fully completed." 
                                : "Payment recorded successfully, remaining pending."}
                        </p>
                    </div>
                ) : step === 1 ? (
                    <>
                        <div className="edit-modal-header-v4">
                            <div className="header-brand-icon-v4">
                                <IndianRupee size={24} />
                            </div>
                            <div className="header-text-content-v4">
                                <h3>Generate Payment</h3>
                                <p>
                                    {serviceType === 'INCOME_TAX'
                                        ? 'Enter the Income Tax (ITR) record ID, then record payment via Income Tax Payments.'
                                        : serviceType === 'CUSTOMER_SERVICE'
                                          ? 'Enter the Customer Service ID to fetch details and record payment.'
                                          : serviceType === 'GST_FILING_RETURN_DETAILS'
                                            ? 'Enter the GST Filing Return Detail ID to fetch details and record payment.'
                                            : 'Select service type and enter ID to fetch details'}
                                </p>
                            </div>
                        </div>

                        <div className="edit-modal-body-v4">
                            <form id="paymentStep1" onSubmit={handleGeneratePayment} className="premium-edit-grid-v4">
                                <div className="input-group-v4 full">
                                    <label><CheckCircle2 size={14} /> Service Type*</label>
                                    <div className="input-wrapper-v4">
                                        <FormCustomSelect
                                            name="serviceType"
                                            value={serviceType}
                                            onChange={(e) => setServiceType(e.target.value)}
                                            options={optionsFromConfigOnly([
                                                { value: 'GST_REGISTRATION', label: 'GST Registration' },
                                                { value: 'GST_FILING', label: 'GST Filing' },
                                                { value: 'GST_FILING_RETURN_DETAILS', label: 'GST Filing Return Detail' },
                                                { value: 'INCOME_TAX', label: 'Income Tax' },
                                                { value: 'CUSTOMER_SERVICE', label: 'Customer Service' },
                                            ])}
                                            placeholder="Service type"
                                            ariaLabel="Service type"
                                            disabled={Boolean(
                                                initialServiceType && SERVICE_TYPES.includes(initialServiceType)
                                            )}
                                        />
                                    </div>
                                </div>

                                <div className="input-group-v4 full">
                                    <label><Tag size={14} />{
                                        serviceType === 'GST_REGISTRATION'
                                            ? 'Registration ID'
                                            : serviceType === 'INCOME_TAX'
                                              ? 'Income Tax (ITR) ID'
                                              : serviceType === 'CUSTOMER_SERVICE'
                                                ? 'Customer Service ID'
                                                : serviceType === 'GST_FILING_RETURN_DETAILS'
                                                  ? 'Return Detail ID'
                                                  : 'Filing ID'
                                    }*</label>
                                    <div className="input-wrapper-v4">
                                        <input
                                            type="number"
                                            placeholder={
                                                serviceType === 'GST_REGISTRATION'
                                                    ? 'Enter Registration ID...'
                                                    : serviceType === 'INCOME_TAX'
                                                      ? 'Enter ITR record ID...'
                                                      : serviceType === 'CUSTOMER_SERVICE'
                                                        ? 'Enter Customer Service ID...'
                                                        : serviceType === 'GST_FILING_RETURN_DETAILS'
                                                          ? 'Enter Return Detail ID...'
                                                          : 'Enter Filing ID...'
                                            }
                                            value={entityIdInput}
                                            onChange={(e) => setEntityIdInput(e.target.value)}
                                            required
                                            autoFocus
                                        />
                                    </div>
                                    {error && <span className="input-error-text" style={{ color: '#ef4444', fontSize: '12px', marginTop: '4px', display: 'flex', alignItems: 'center', gap: '4px' }}><AlertCircle size={12} /> {error}</span>}
                                </div>
                            </form>
                        </div>

                        <div className="edit-modal-footer-v4">
                            <button type="button" className="btn-cancel-v4" onClick={onBack}>Cancel</button>
                            <button type="submit" form="paymentStep1" className="btn-save-v4" disabled={generating || !entityIdInput}>
                                {generating ? (
                                    <><Loader2 size={16} className="spin" style={{ marginRight: '8px' }} /> Fetching...</>
                                ) : (
                                    <>Generate Payment <ArrowRight size={16} style={{ marginLeft: '8px' }} /></>
                                )}
                            </button>
                        </div>
                    </>
                ) : (
                    <>
                        <div className="edit-modal-header-v4">
                            <div className="header-brand-icon-v4">
                                <Wallet size={24} />
                            </div>
                            <div className="header-text-content-v4">
                                <h3>New Payment</h3>
                                <p>Verify details and create the payment record</p>
                            </div>
                        </div>

                        <div className="edit-modal-body-v4">
                            <form id="paymentStep2" onSubmit={handleSubmit} className="premium-edit-grid-v4">
                                <div className="input-group-v4 full">
                                    <div className="selected-badge-v2" style={{ margin: '0 0 16px 0', background: 'rgba(46, 184, 122, 0.1)', color: '#2eb87a', borderRadius: '12px', padding: '12px', display: 'flex', flexDirection: 'column', gap: '4px', fontSize: '13px' }}>
                                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontWeight: '700' }}>
                                            <CheckCircle2 size={14} />
                                            <span>Type: {
                                                backendData.entity_type === 'GST_REGISTRATION'
                                                    ? 'Registration'
                                                    : backendData.entity_type === 'GST_FILING'
                                                      ? 'Filing'
                                                      : backendData.entity_type === 'GST_FILING_RETURN_DETAILS'
                                                        ? 'GST Filing Return Detail'
                                                        : backendData.entity_type === 'CUSTOMER_SERVICE'
                                                          ? 'Customer Service'
                                                          : 'Income Tax'
                                            }</span>
                                        </div>
                                        <div style={{ marginLeft: '22px', color: 'var(--text-primary)' }}>
                                            Target: <strong>{backendData.target_label || buildPaymentTargetLabel(
                                                backendData.target_code || backendData.gstin,
                                                backendData.customer_name,
                                                backendData.business_name,
                                                backendData.entity_id,
                                            )}</strong>
                                        </div>
                                    </div>
                                </div>

                                <div className="input-group-v4">
                                    <label><Tag size={14} /> Original Amount</label>
                                    <div className="input-wrapper-v4">
                                        {canEditOriginalAmount ? (
                                            <input
                                                type="number"
                                                name="original_amount"
                                                placeholder="Enter bill amount"
                                                value={formData.original_amount}
                                                onChange={handleChange}
                                                min="0.01"
                                                step="0.01"
                                                disabled={isFormDisabled}
                                            />
                                        ) : (
                                            <input
                                                type="text"
                                                value={effectiveOriginal.toFixed(2)}
                                                disabled
                                                className="read-only-input"
                                            />
                                        )}
                                    </div>
                                    {canEditOriginalAmount && (
                                        <span className="input-hint-text" style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '4px' }}>
                                            {backendData?.entity_type === 'GST_FILING_RETURN_DETAILS'
                                                ? 'Enter the service fee for this return period when no price is configured'
                                                : 'Enter the service fee when no price is configured for this filing'}
                                        </span>
                                    )}
                                </div>

                                <div className="input-group-v4">
                                    <label><Tag size={14} /> Total Discount</label>
                                    <div className="input-wrapper-v4">
                                        <input type="text" value={(parseFloat(backendData.total_discount) || 0).toFixed(2)} disabled className="read-only-input" />
                                    </div>
                                </div>

                                <div className="input-group-v4">
                                    <label><Tag size={14} /> Total Paid</label>
                                    <div className="input-wrapper-v4">
                                        <input type="text" value={(parseFloat(backendData.total_paid) || 0).toFixed(2)} disabled className="read-only-input" />
                                    </div>
                                </div>

                                <div className="input-group-v4">
                                    <label><IndianRupee size={14} /> Remaining Amount</label>
                                    <div className="input-wrapper-v4 highlighted">
                                        <input
                                            type="text"
                                            value={remaining_amount.toFixed(2)}
                                            disabled
                                            style={{ color: '#ef4444', fontWeight: '800', border: '1px solid rgba(239, 68, 68, 0.3)', background: 'rgba(239, 68, 68, 0.05)' }}
                                        />
                                    </div>
                                </div>

                                <div className="input-group-v4">
                                    <label><Tag size={14} /> New Discount (this payment)</label>
                                    <div className="input-wrapper-v4">
                                        <input
                                            type="number"
                                            name="discount"
                                            placeholder="0.00"
                                            value={formData.discount}
                                            onChange={handleChange}
                                            min="0"
                                            max={remaining_amount}
                                            step="0.01"
                                            disabled={isFormDisabled}
                                        />
                                    </div>
                                </div>

                                <div className="input-group-v4">
                                    <label><Wallet size={14} /> Cash paid (this payment)</label>
                                    <div className="input-wrapper-v4">
                                        <input
                                            type="number"
                                            name="paid_amount"
                                            placeholder="0.00"
                                            value={formData.paid_amount}
                                            onChange={handleChange}
                                            min="0"
                                            max={payable}
                                            step="0.01"
                                            disabled={isFormDisabled}
                                        />
                                    </div>
                                </div>

                                <div className="input-group-v4">
                                    <label><IndianRupee size={14} /> Due after discount</label>
                                    <div className="input-wrapper-v4">
                                        <input type="text" value={payable.toFixed(2)} disabled style={{ color: '#2eb87a', fontWeight: '700', background: 'rgba(46, 184, 122, 0.05)' }} />
                                    </div>
                                    <span className="input-hint-text" style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '4px' }}>
                                        Set discount and/or cash; full waiver: discount = remaining, cash = 0
                                    </span>
                                </div>

                                <div className="input-group-v4">
                                    {/* Placeholder to keep alignment */}
                                </div>

                                <div className="input-group-v4 full">
                                    <label><MessageSquare size={14} /> Remarks</label>
                                    <div className="input-wrapper-v4">
                                        <textarea
                                            name="remarks"
                                            placeholder="Add any internal remarks here..."
                                            value={formData.remarks}
                                            onChange={handleChange}
                                            rows="3"
                                            disabled={isFormDisabled}
                                        ></textarea>
                                    </div>
                                    {error && <span className="input-error-text" style={{ color: '#ef4444', fontSize: '13px', marginTop: '12px', display: 'flex', alignItems: 'center', gap: '6px', padding: '10px', background: 'rgba(239, 68, 68, 0.1)', borderRadius: '8px' }}><AlertCircle size={14} /> {error}</span>}
                                </div>
                            </form>
                        </div>

                        <div className="edit-modal-footer-v4">
                            <button type="button" className="btn-cancel-v4" onClick={() => setStep(1)} disabled={submitting || isFormDisabled}>Back</button>
                            <button type="submit" form="paymentStep2" className="btn-save-v4" disabled={submitting || isInvalid || isFormDisabled}>
                                {submitting ? (
                                    <><Loader2 size={16} className="spin" style={{ marginRight: '8px' }} /> Processing...</>
                                ) : (
                                    <>Pay Now</>
                                )}
                            </button>
                        </div>
                    </>
                )}
            </div>
        </div>
    );
};

export default AddPayment;
