import React, { useEffect, useMemo, useState } from 'react';
import { createPortal } from 'react-dom';
import {
    X,
    User,
    Phone,
    Briefcase,
    Activity,
    Clock,
    Hash,
    FileText,
    Loader2,
    AlertCircle,
} from 'lucide-react';
import { formatCrmLeadDateTime } from './crmLeadTableConfig';
import { getFollowupActivityBadge } from '../../utils/followupsApi';
import { fetchGstRegistrationFull, fetchIncomeTaxByEntityId } from './crmLeadViewApi';

const VIEW_SECTIONS = [
    {
        id: 'contact',
        title: 'Contact',
        icon: User,
        fields: ['mobile', 'full_name', 'email', 'preferred_language'],
    },
    {
        id: 'pipeline',
        title: 'Pipeline',
        icon: Briefcase,
        fields: [
            'stage',
            'entity_type',
            'entity_id',
            'follow_up_status',
            'followup_at',
            'lead_type',
            'lead_source',
            'tag',
            'remarks',
        ],
    },
    {
        id: 'assignment',
        title: 'Assignment',
        icon: Phone,
        fields: ['rm_id', 'rm_name', 'op_id', 'op_name'],
    },
    {
        id: 'calls',
        title: 'Call activity',
        icon: Activity,
        fields: [
            'call_attempted_count',
            'call_connected_count',
            'last_dailed_at',
            'last_connected_at',
            'completed_at',
            'missed_at',
        ],
    },
    {
        id: 'meta',
        title: 'Record',
        icon: Clock,
        fields: ['id', 'is_active', 'created_at', 'updated_at'],
    },
];

const GST_REGISTRATION_SECTION = {
    id: 'gst-registration',
    title: 'GST Registration',
    icon: Briefcase,
    fields: [
        'id',
        'business_name',
        'legal_name',
        'username',
        'gstin',
        'pan',
        'registration_type',
        'ownership_category',
        'business_type',
        'registration_status',
        'filing_preference',
        'is_filing_needed',
        'is_rcm_applicable',
        'state',
        'city',
        'mobile',
        'email',
        'secondary_email',
        'rm_name',
        'created_by_name',
        'customer_id',
        'created_at',
        'updated_at',
    ],
};

const GST_PERSONS_SECTION = {
    id: 'gst-persons',
    title: 'Associated people',
    icon: User,
    fields: [],
};

const INCOME_TAX_SECTIONS = [
    {
        id: 'itr-client',
        title: 'Client',
        icon: User,
        fields: [
            'client_name',
            'pan_number',
            'mobile',
            'email_id',
            'referral_phone_number',
            'language',
            'state',
        ],
    },
    {
        id: 'itr-filing',
        title: 'Filing',
        icon: FileText,
        fields: [
            'year',
            'financial_year',
            'source_of_income',
            'filed_status',
            'filing_date',
            'refund_amount',
            'priority',
            'remarks',
        ],
    },
    {
        id: 'itr-assignment',
        title: 'Assignment',
        icon: Phone,
        fields: ['rm_id', 'rm_name', 'op_id', 'op_name'],
    },
    {
        id: 'itr-meta',
        title: 'Income tax record',
        icon: Clock,
        fields: ['id', 'is_active', 'created_at', 'updated_at'],
    },
];

const FIELD_LABELS = {
    id: 'Lead ID',
    mobile: 'Mobile',
    full_name: 'Full Name',
    email: 'Email',
    entity_id: 'Entity ID',
    entity_type: 'Entity Type',
    preferred_language: 'Preferred Language',
    stage: 'Stage',
    call_attempted_count: 'Call Attempts',
    call_connected_count: 'Call Connected',
    follow_up_status: 'Follow-up Status',
    followup_at: 'Follow-up At',
    rm_id: 'RM ID',
    op_id: 'OP ID',
    rm_name: 'RM Name',
    op_name: 'OP Name',
    remarks: 'Remarks',
    lead_type: 'Lead Type',
    ay: 'Assessment Year',
    tag: 'Tag',
    lead_source: 'Lead Source',
    last_dailed_at: 'Last Dialed At',
    last_connected_at: 'Last Connected At',
    completed_at: 'Completed At',
    missed_at: 'Missed At',
    is_active: 'Status',
    created_at: 'Created At',
    updated_at: 'Updated At',
    client_name: 'Client Name',
    pan_number: 'PAN',
    email_id: 'Email',
    referral_phone_number: 'Referrer Phone',
    language: 'Language',
    state: 'State',
    year: 'Record Year',
    financial_year: 'Financial Year',
    source_of_income: 'Source of Income',
    filed_status: 'Filing Status',
    filing_date: 'Filing Date',
    refund_amount: 'Refund Amount',
    priority: 'Priority',
    business_name: 'Business Name',
    legal_name: 'Legal Name',
    username: 'Username',
    gstin: 'GSTIN',
    pan: 'PAN',
    registration_type: 'Registration Type',
    ownership_category: 'Ownership Category',
    business_type: 'Business Type',
    registration_status: 'Registration Status',
    filing_preference: 'Filing Preference',
    is_filing_needed: 'Filing Needed',
    is_rcm_applicable: 'RCM Applicable',
    secondary_email: 'Secondary Email',
    created_by_name: 'Created By',
    customer_id: 'Customer ID',
};

function formatLabel(key) {
    return FIELD_LABELS[key]
        || key.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}

function formatViewValue(key, value) {
    if (value == null || value === '') return null;
    if (typeof value === 'boolean') return value ? 'Active' : 'Inactive';
    if (Array.isArray(value)) {
        if (value.length === 0) return null;
        return value.map((v) => String(v).replace(/_/g, ' ')).join(', ');
    }
    if (
        key.endsWith('_at')
        || key.endsWith('_date')
        || key === 'followup_at'
        || key === 'filing_date'
    ) {
        return formatCrmLeadDateTime(value);
    }
    if (key === 'refund_amount' && typeof value === 'number') {
        return `₹ ${value.toLocaleString('en-IN')}`;
    }
    if (typeof value === 'object') return JSON.stringify(value);
    return String(value);
}

function FieldValue({ fieldKey, value, lead }) {
    const display = formatViewValue(fieldKey, value);

    if (display == null) {
        return <span className="crm-view-field-empty">Not set</span>;
    }

    if (fieldKey === 'registration_status') {
        return (
            <span className={`stage-badge crm-view-stage-badge ${String(value).toLowerCase()}`}>
                {String(value).replace(/_/g, ' ')}
            </span>
        );
    }

    if (fieldKey === 'is_filing_needed' || fieldKey === 'is_rcm_applicable') {
        return <span>{value ? 'Yes' : 'No'}</span>;
    }

    if (fieldKey === 'stage' || fieldKey === 'filed_status') {
        return (
            <span className={`stage-badge crm-view-stage-badge ${String(value).toLowerCase()}`}>
                {String(value).replace(/_/g, ' ')}
            </span>
        );
    }

    if (fieldKey === 'follow_up_status') {
        const { statusBadgeClass, statusTextString } = getFollowupActivityBadge(lead || {});
        return (
            <span className={`status-badge crm-view-status-badge followup-status-badge ${statusBadgeClass}`}>
                {statusTextString}
            </span>
        );
    }

    if (fieldKey === 'is_active') {
        return (
            <span className={`crm-view-active-pill ${value ? 'is-active' : 'is-inactive'}`}>
                {display}
            </span>
        );
    }

    if (fieldKey === 'mobile' || fieldKey === 'email' || fieldKey === 'email_id' || fieldKey === 'pan_number') {
        return <span className="crm-view-field-accent">{display}</span>;
    }

    if (fieldKey === 'remarks') {
        return <span className="crm-view-field-remarks">{display}</span>;
    }

    return <span>{display}</span>;
}

function buildSections(record, sectionDefs, { idLabel } = {}) {
    const used = new Set();
    const sections = sectionDefs.map((section) => {
        const items = section.fields
            .filter((key) => key in record && !used.has(key))
            .map((key) => {
                used.add(key);
                const label = key === 'id' && idLabel ? idLabel : formatLabel(key);
                return { key, label, value: record[key] };
            })
            .filter((item) => item.value !== undefined);

        return { ...section, items };
    }).filter((s) => s.items.length > 0);

    const extra = Object.keys(record)
        .filter((k) => k !== 'history' && !used.has(k))
        .map((key) => ({ key, label: formatLabel(key), value: record[key] }));

    if (extra.length > 0) {
        sections.push({
            id: 'other',
            title: 'Other',
            icon: Hash,
            items: extra,
        });
    }

    return sections;
}

function buildGstPersonsSection(persons) {
    if (!Array.isArray(persons) || persons.length === 0) return null;

    const items = persons.flatMap((person, idx) => {
        const prefix = persons.length > 1 ? `Person ${idx + 1}` : 'Person';
        return [
            { key: `person_${idx}_name`, label: `${prefix} — Name`, value: person.full_name },
            { key: `person_${idx}_designation`, label: 'Designation', value: person.designation },
            { key: `person_${idx}_pan`, label: 'PAN', value: person.pan },
            { key: `person_${idx}_mobile`, label: 'Mobile', value: person.mobile },
            { key: `person_${idx}_email`, label: 'Email', value: person.email },
        ].filter((item) => item.value != null && item.value !== '');
    });

    if (items.length === 0) return null;
    return { ...GST_PERSONS_SECTION, items };
}

const GST_UNLINKED_MSG = 'No GST registration linked. Use Push to create and link a registration.';
const ITR_UNLINKED_MSG = 'No income tax record linked. Use Push to create and link an ITR record.';

export default function CrmLeadViewDrawer({ lead, entityType, onClose }) {
    const [incomeTaxRecord, setIncomeTaxRecord] = useState(null);
    const [incomeTaxLoading, setIncomeTaxLoading] = useState(false);
    const [incomeTaxUnlinked, setIncomeTaxUnlinked] = useState(false);
    const [incomeTaxError, setIncomeTaxError] = useState(null);
    const [gstFullData, setGstFullData] = useState(null);
    const [gstLoading, setGstLoading] = useState(false);
    const [gstUnlinked, setGstUnlinked] = useState(false);
    const [gstError, setGstError] = useState(null);

    const entityTypeNorm = (entityType || '').trim().toUpperCase();
    const isIncomeTaxCrm = entityTypeNorm === 'INCOME_TAX';
    const isGstCrm = entityTypeNorm === 'GST_REGISTRATION';
    const entityId = lead?.entity_id;

    useEffect(() => {
        if (!lead || !isIncomeTaxCrm) {
            setIncomeTaxRecord(null);
            setIncomeTaxUnlinked(false);
            setIncomeTaxError(null);
            setIncomeTaxLoading(false);
            return undefined;
        }

        if (entityId == null || entityId === '') {
            setIncomeTaxRecord(null);
            setIncomeTaxUnlinked(true);
            setIncomeTaxError(null);
            setIncomeTaxLoading(false);
            return undefined;
        }

        let cancelled = false;
        setIncomeTaxLoading(true);
        setIncomeTaxUnlinked(false);
        setIncomeTaxError(null);
        setIncomeTaxRecord(null);

        fetchIncomeTaxByEntityId(entityId)
            .then((record) => {
                if (cancelled) return;
                if (!record) {
                    setIncomeTaxError(`Income tax record ${entityId} was not found.`);
                    return;
                }
                setIncomeTaxRecord(record);
            })
            .catch(() => {
                if (!cancelled) {
                    setIncomeTaxError('Failed to load income tax details. Please try again.');
                }
            })
            .finally(() => {
                if (!cancelled) setIncomeTaxLoading(false);
            });

        return () => {
            cancelled = true;
        };
    }, [lead, isIncomeTaxCrm, entityId]);

    useEffect(() => {
        if (!lead || !isGstCrm) {
            setGstFullData(null);
            setGstUnlinked(false);
            setGstError(null);
            setGstLoading(false);
            return undefined;
        }

        if (entityId == null || entityId === '') {
            setGstFullData(null);
            setGstUnlinked(true);
            setGstError(null);
            setGstLoading(false);
            return undefined;
        }

        let cancelled = false;
        setGstLoading(true);
        setGstUnlinked(false);
        setGstError(null);
        setGstFullData(null);

        fetchGstRegistrationFull(entityId)
            .then((data) => {
                if (cancelled) return;
                if (!data?.registration) {
                    setGstError(`GST registration ${entityId} was not found.`);
                    return;
                }
                setGstFullData(data);
            })
            .catch(() => {
                if (!cancelled) {
                    setGstError('Failed to load GST registration details. Please try again.');
                }
            })
            .finally(() => {
                if (!cancelled) setGstLoading(false);
            });

        return () => {
            cancelled = true;
        };
    }, [lead, isGstCrm, entityId]);

    const sections = useMemo(() => {
        if (!lead) return [];

        const pipelineFields = [
            'stage',
            'entity_type',
            'entity_id',
            'follow_up_status',
            'followup_at',
            'lead_type',
            'lead_source',
            'tag',
            'remarks',
        ];
        if (isIncomeTaxCrm) {
            pipelineFields.splice(6, 0, 'ay');
        }

        const viewSections = VIEW_SECTIONS.map((section) => (
            section.id === 'pipeline'
                ? { ...section, fields: pipelineFields }
                : section
        ));

        let leadSections = buildSections(lead, viewSections);

        if (isIncomeTaxCrm && incomeTaxRecord) {
            const itrSections = buildSections(incomeTaxRecord, INCOME_TAX_SECTIONS, {
                idLabel: 'Income Tax ID',
            });
            leadSections = [...leadSections, ...itrSections];
        }

        if (isGstCrm && gstFullData?.registration) {
            const gstSections = buildSections(gstFullData.registration, [GST_REGISTRATION_SECTION], {
                idLabel: 'Registration ID',
            });
            const gstSection = gstSections[0];
            const personsSection = buildGstPersonsSection(gstFullData.persons);
            leadSections = [
                ...leadSections,
                ...(gstSection ? [gstSection] : []),
                ...(personsSection ? [personsSection] : []),
            ];
        }

        return leadSections;
    }, [lead, isIncomeTaxCrm, incomeTaxRecord, isGstCrm, gstFullData]);

    if (!lead) return null;

    const title = lead.full_name || incomeTaxRecord?.client_name || 'Unnamed lead';
    const subtitleMobile = lead.mobile || incomeTaxRecord?.mobile;
    const subtitle = subtitleMobile
        ? `+91 ${String(subtitleMobile).replace(/^\+?91/, '')}`
        : `Lead ${lead.id}`;

    return createPortal(
        <div
            className="crm-lead-details-drawer-overlay"
            onClick={onClose}
            role="presentation"
        >
            <div
                className="crm-lead-details-drawer"
                onClick={(e) => e.stopPropagation()}
                role="dialog"
                aria-labelledby="crm-lead-view-title"
            >
                <header className="crm-view-drawer-hero">
                    <button
                        type="button"
                        className="crm-view-close-btn"
                        onClick={onClose}
                        aria-label="Close"
                    >
                        <X size={18} />
                    </button>
                    <div className="crm-view-hero-content">
                        <div className="crm-view-avatar">
                            {(title[0] || '?').toUpperCase()}
                        </div>
                        <div className="crm-view-hero-text">
                            <h3 id="crm-lead-view-title">{title}</h3>
                            <p className="crm-view-hero-sub">{subtitle}</p>
                            <div className="crm-view-hero-badges">
                                {lead.stage && (
                                    <span className={`stage-badge crm-view-stage-badge ${String(lead.stage).toLowerCase()}`}>
                                        {lead.stage}
                                    </span>
                                )}
                                {lead.entity_type && (
                                    <span className="crm-view-entity-pill">{lead.entity_type}</span>
                                )}
                                {entityId != null && entityId !== '' && isIncomeTaxCrm && (
                                    <span className="crm-view-id-pill">ITR {entityId}</span>
                                )}
                                {entityId != null && entityId !== '' && isGstCrm && (
                                    <span className="crm-view-id-pill">GST {entityId}</span>
                                )}
                                {lead.id != null && (
                                    <span className="crm-view-id-pill">Lead {lead.id}</span>
                                )}
                                {isIncomeTaxCrm && lead.ay && (
                                    <span className="crm-view-id-pill">AY {lead.ay}</span>
                                )}
                            </div>
                        </div>
                    </div>
                </header>

                <div className="crm-lead-view-body">
                    {sections.map((section) => {
                        const Icon = section.icon;
                        return (
                            <section key={section.id} className="crm-view-section">
                                <div className="crm-view-section-head">
                                    <Icon size={15} strokeWidth={2.25} />
                                    <h4>{section.title}</h4>
                                </div>
                                <div className="crm-view-fields-grid">
                                    {section.items.map(({ key, label, value }) => (
                                        <div
                                            key={key}
                                            className={`crm-view-field${key === 'remarks' ? ' crm-view-field--wide' : ''}`}
                                        >
                                            <span className="crm-view-field-label">{label}</span>
                                            <div className="crm-view-field-value">
                                                <FieldValue fieldKey={key} value={value} lead={lead} />
                                            </div>
                                        </div>
                                    ))}
                                </div>
                            </section>
                        );
                    })}

                    {isIncomeTaxCrm && incomeTaxLoading && (
                        <div className="crm-view-fetch-state crm-view-gst-footer-state">
                            <Loader2 size={22} className="spin" />
                            <span>Loading income tax record…</span>
                        </div>
                    )}

                    {isIncomeTaxCrm && !incomeTaxLoading && incomeTaxUnlinked && (
                        <div className="crm-view-fetch-state crm-view-fetch-state--info crm-view-gst-footer-state">
                            <AlertCircle size={20} />
                            <span>{ITR_UNLINKED_MSG}</span>
                        </div>
                    )}

                    {isIncomeTaxCrm && !incomeTaxLoading && !incomeTaxUnlinked && incomeTaxError && (
                        <div className="crm-view-fetch-state crm-view-fetch-state--error crm-view-gst-footer-state">
                            <AlertCircle size={20} />
                            <span>{incomeTaxError}</span>
                        </div>
                    )}

                    {isGstCrm && gstLoading && (
                        <div className="crm-view-fetch-state crm-view-gst-footer-state">
                            <Loader2 size={22} className="spin" />
                            <span>Loading GST registration…</span>
                        </div>
                    )}

                    {isGstCrm && !gstLoading && gstUnlinked && (
                        <div className="crm-view-fetch-state crm-view-fetch-state--info crm-view-gst-footer-state">
                            <AlertCircle size={20} />
                            <span>{GST_UNLINKED_MSG}</span>
                        </div>
                    )}

                    {isGstCrm && !gstLoading && !gstUnlinked && gstError && (
                        <div className="crm-view-fetch-state crm-view-fetch-state--error crm-view-gst-footer-state">
                            <AlertCircle size={20} />
                            <span>{gstError}</span>
                        </div>
                    )}
                </div>
            </div>
        </div>,
        document.body
    );
}
