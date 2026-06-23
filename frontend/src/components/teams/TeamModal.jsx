import React, { useState, useEffect } from 'react';
import {
    X,
    Shield,
    FileText,
    CheckCircle2,
    AlertCircle,
    Loader2,
    Briefcase
} from 'lucide-react';
import api from '../../utils/api';

const TeamModal = ({ isOpen, onClose, onSave, team = null }) => {
    const [formData, setFormData] = useState({
        team_code: '',
        team_name: ''
    });
    const [loading, setLoading] = useState(false);
    const [errors, setErrors] = useState({});

    useEffect(() => {
        if (team) {
            setFormData({
                team_code: team.team_code || '',
                team_name: team.team_name || ''
            });
        } else {
            setFormData({
                team_code: '',
                team_name: ''
            });
        }
        setErrors({});
    }, [team, isOpen]);

    const handleChange = (e) => {
        const { name, value } = e.target;
        setFormData(prev => ({ ...prev, [name]: value }));
        if (errors[name]) {
            setErrors(prev => ({ ...prev, [name]: null }));
        }
    };

    const handleSubmit = async (e) => {
        e.preventDefault();
        setLoading(true);
        setErrors({});

        try {
            if (team) {
                // Edit existing team - Note: Currently teams_api.py doesn't have an edit endpoint
                // I might need to add one or just handle creation for now.
                // Assuming we'll add /app/v1/teams/edit/{id}
                await api.post(`/app/v1/teams/edit/${team.id}`, formData);
            } else {
                // Create new team
                // The /create endpoint expects team_code and team_name as query params based on teams_api.py
                await api.post(`/app/v1/teams/create?team_code=${formData.team_code}&team_name=${formData.team_name}`);
            }
            onSave();
            onClose();
        } catch (err) {
            console.error('Failed to save team:', err);
            if (err.fields) {
                setErrors(err.fields);
            }
            setErrors(prev => ({ ...prev, _global: err.message || 'An unexpected error occurred.' }));
        } finally {
            setLoading(false);
        }
    };

    if (!isOpen) return null;

    return (
        <div className="premium-filter-overlay show" onClick={onClose}>
            <div className="premium-edit-modal-v4" style={{ maxWidth: '500px' }} onClick={e => e.stopPropagation()}>
                <div className="edit-modal-header-v4" style={{ padding: '24px 32px', borderBottom: '1px solid rgba(var(--fg-rgb),0.05)' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
                        <div className="header-brand-icon-v4" style={{ width: '48px', height: '48px' }}>
                            <Shield size={24} />
                        </div>
                        <div>
                            <h3 style={{ margin: 0, fontSize: '20px', fontWeight: 600 }}>{team ? 'Edit Team' : 'Create New Team'}</h3>
                            <p style={{ margin: 0, fontSize: '12px', color: 'var(--text-muted)' }}>{team ? 'Update team identity and configuration' : 'Establish a new organizational unit'}</p>
                        </div>
                    </div>
                    <button className="btn-close-modal-v4-top" onClick={onClose}>
                        <X size={20} />
                    </button>
                </div>

                <form onSubmit={handleSubmit} style={{ padding: '32px' }}>
                    {errors._global && (
                        <div className="modal-global-error-banner" style={{ marginBottom: '24px' }}>
                            <AlertCircle size={16} />
                            <span>{errors._global}</span>
                        </div>
                    )}

                    <div className="premium-edit-grid-v4" style={{ gridTemplateColumns: '1fr' }}>
                        <div className="input-group-v4 full">
                            <label><FileText size={14} /> Team Code</label>
                            <div className="input-wrapper-v4">
                                <input
                                    type="text"
                                    name="team_code"
                                    value={formData.team_code}
                                    onChange={handleChange}
                                    placeholder="e.g. SALES_NORTH"
                                    required
                                    style={{ textTransform: 'uppercase' }}
                                />
                            </div>
                            {errors.team_code && <span className="input-error-text"><AlertCircle size={12} /> {errors.team_code}</span>}
                        </div>

                        <div className="input-group-v4 full">
                            <label><Briefcase size={14} /> Team Name</label>
                            <div className="input-wrapper-v4">
                                <input
                                    type="text"
                                    name="team_name"
                                    value={formData.team_name}
                                    onChange={handleChange}
                                    placeholder="e.g. Northern Sales Group"
                                    required
                                />
                            </div>
                            {errors.team_name && <span className="input-error-text"><AlertCircle size={12} /> {errors.team_name}</span>}
                        </div>
                    </div>

                    <div className="edit-modal-footer-v4" style={{ marginTop: '32px', padding: 0, background: 'transparent', border: 'none' }}>
                        <button type="button" className="btn-cancel-v4" onClick={onClose} disabled={loading}>
                            Cancel
                        </button>
                        <button type="submit" className="btn-save-v4" disabled={loading}>
                            {loading ? (
                                <>
                                    <Loader2 className="spin" size={16} />
                                    <span>Saving...</span>
                                </>
                            ) : (
                                <>
                                    <CheckCircle2 size={16} />
                                    <span>{team ? 'Update Team' : 'Create Team'}</span>
                                </>
                            )}
                        </button>
                    </div>
                </form>
            </div>
        </div>
    );
};

export default TeamModal;
