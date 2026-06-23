import { useState, useEffect, useCallback } from 'react';
import api from '../../utils/api';

const EMPTY_MAPPINGS = { stage_to_pitch: [], pitch_to_statuses: {} };

export function useCrmLeadMappings(entityType) {
    const [mappingData, setMappingData] = useState(EMPTY_MAPPINGS);
    const [stages, setStages] = useState([]);
    const [loading, setLoading] = useState(true);

    const fetchMappings = useCallback(async () => {
        setLoading(true);
        try {
            const apiBase = '/api/v1/crm/leads';
            const et = (entityType || '').trim().toUpperCase();
            const [mappingRes, stagesRes] = await Promise.all([
                api.get(`${apiBase}/ui-mappings`, { params: { entity_type: et } }),
                api.get(`${apiBase}/stages`, { params: { entity_type: et } }),
            ]);
            setMappingData(mappingRes.data || EMPTY_MAPPINGS);
            setStages(stagesRes.data?.stages || []);
        } catch (err) {
            console.error('Failed to fetch CRM UI mappings:', err);
            setMappingData(EMPTY_MAPPINGS);
            setStages([]);
        } finally {
            setLoading(false);
        }
    }, [entityType]);

    useEffect(() => {
        fetchMappings();
    }, [fetchMappings]);

    return { mappingData, stages, loading, refetchMappings: fetchMappings };
}
