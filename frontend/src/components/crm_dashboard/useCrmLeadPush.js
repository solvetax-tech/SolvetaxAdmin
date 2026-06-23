import { useState, useCallback, useEffect } from 'react';
import { createIncomeTaxLead, getIncomeTaxErrorPayload } from '../../utils/incomeTaxApi';
import { createGstRegistrationLead, getGstRegistrationErrorPayload } from '../../utils/gstRegistrationApi';

const GST_PUSH_STAGE = 'PENDING_REGISTRATION_DATA';

/**
 * One-time Push from CRM leads table:
 * - INCOME_TAX → POST /api/v1/income-tax/lead
 * - GST_REGISTRATION (PENDING_REGISTRATION_DATA only) → POST /api/v1/gst-registrations/lead
 */
export function useCrmLeadPush(entityType, setLeads) {
    const [pushingLeadId, setPushingLeadId] = useState(null);
    const [pushedLeadIds, setPushedLeadIds] = useState(() => new Set());
    const [pushFeedback, setPushFeedback] = useState(null);

    const entityNorm = (entityType || '').trim().toUpperCase();
    const isIncomeTaxCrm = entityNorm === 'INCOME_TAX';
    const isGstCrm = entityNorm === 'GST_REGISTRATION';

    const isLeadPushed = useCallback(
        (lead) => {
            if (!lead) return false;
            if (lead.entity_id != null && lead.entity_id !== '') return true;
            return pushedLeadIds.has(lead.id);
        },
        [pushedLeadIds]
    );

    useEffect(() => {
        setPushFeedback(null);
        setPushedLeadIds(new Set());
    }, [entityType]);

    const handlePush = useCallback(
        async (e, lead) => {
            e.stopPropagation();
            if (isLeadPushed(lead) || pushingLeadId != null) return;

            const mobile = String(lead.mobile || '').replace(/\D/g, '').slice(0, 10);
            if (mobile.length !== 10) {
                setPushFeedback({
                    type: 'error',
                    text: 'Lead must have a valid 10-digit mobile to push.',
                });
                return;
            }

            const fullName = (lead.full_name || '').trim() || mobile;
            const stage = String(lead.stage || '').trim().toUpperCase();

            if (isGstCrm) {
                if (stage !== GST_PUSH_STAGE) {
                    setPushFeedback({
                        type: 'error',
                        text: `Push is only available for ${GST_PUSH_STAGE} leads.`,
                    });
                    return;
                }
            } else if (!isIncomeTaxCrm) {
                return;
            }

            setPushingLeadId(lead.id);
            setPushFeedback(null);

            const basePayload = {
                crm_lead_id: lead.id,
                mobile,
                full_name: fullName,
                email: lead.email || undefined,
                preferred_language: lead.preferred_language || undefined,
                rm_id: lead.rm_id || undefined,
                op_id: lead.op_id || undefined,
            };

            try {
                if (isGstCrm) {
                    const result = await createGstRegistrationLead({
                        ...basePayload,
                        remarks: 'Pushed from CRM GST lead.',
                    });
                    const gstId = result?.gst_registration_id;
                    setLeads((prev) =>
                        prev.map((row) =>
                            row.id === lead.id
                                ? { ...row, entity_id: gstId ?? row.entity_id }
                                : row
                        )
                    );
                    setPushedLeadIds((prev) => new Set(prev).add(lead.id));
                    setPushFeedback({
                        type: 'success',
                        text: result?.message || `Pushed to GST registration (record ${gstId}).`,
                    });
                    return;
                }

                const result = await createIncomeTaxLead({
                    ...basePayload,
                    remarks: 'Pushed from CRM ITR lead.',
                });
                const incomeTaxId = result?.income_tax_id;
                setLeads((prev) =>
                    prev.map((row) =>
                        row.id === lead.id
                            ? { ...row, entity_id: incomeTaxId ?? row.entity_id }
                            : row
                    )
                );
                setPushedLeadIds((prev) => new Set(prev).add(lead.id));
                setPushFeedback({
                    type: 'success',
                    text: result?.message || `Pushed to ITR (record ${incomeTaxId}).`,
                });
            } catch (err) {
                const structured = isGstCrm
                    ? getGstRegistrationErrorPayload(err)
                    : getIncomeTaxErrorPayload(err);
                const detail =
                    structured?.message
                    || structured?.fields?.crm_lead_id
                    || structured?.fields?.mobile
                    || structured?.fields?.stage
                    || err?.response?.data?.detail
                    || err?.message
                    || (isGstCrm ? 'Push to GST registration failed.' : 'Push to ITR failed.');
                setPushFeedback({ type: 'error', text: String(detail) });
            } finally {
                setPushingLeadId(null);
            }
        },
        [isGstCrm, isIncomeTaxCrm, isLeadPushed, pushingLeadId, setLeads]
    );

    return {
        isIncomeTaxCrm,
        isGstCrm,
        isLeadPushed,
        handlePush,
        /** @deprecated use handlePush */
        handlePushToIncomeTax: handlePush,
        pushingLeadId,
        pushFeedback,
    };
}

/** @deprecated import useCrmLeadPush */
export { useCrmLeadPush as useCrmIncomeTaxPush };
