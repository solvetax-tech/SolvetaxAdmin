/**
 * @file UploadDocuments.jsx
 * @description Component interface allowing administrators to submit new
 * compliance files and associate them with a specified GST Registration ID.
 */
import React, { useEffect, useMemo, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { X, Hash, FileText, Link as LinkIcon, CheckCircle2, AlertCircle, RotateCcw, Upload, File as FileIcon, Trash2 } from 'lucide-react';
import { createPortal } from 'react-dom';
import './GSTRegistrationSignup.css';
import './UploadDocuments.css';
import api from '../../utils/api';
import FormCustomSelect from '../common/FormCustomSelect';
import { optionsFromConfig } from '../common/selectOptionUtils';

const UploadDocuments = ({ isOpen = true, onClose, mode: modeProp, initialPersonId }) => {
    const [formData, setFormData] = useState({
        person_id: '',
        document_type: '',
        document_url: '',
        verified: false,
    });

    const [loading, setLoading] = useState(false);
    const [fetchingDocs, setFetchingDocs] = useState(false);
    const [requiredDocs, setRequiredDocs] = useState([]);
    const [uploadMethod, setUploadMethod] = useState('file'); // 'file' or 'link'
    const [selectedFile, setSelectedFile] = useState(null);
    const [error, setError] = useState('');
    const [success, setSuccess] = useState(false);
    const location = useLocation();
    const navigate = useNavigate();

    const resolvedMode = useMemo(() => {
        if (modeProp) return modeProp;
        const initialStep = location?.state?.initialStep;
        return initialStep === 2 ? 'details' : 'upload';
    }, [modeProp, location?.state?.initialStep]);

    const handleClose = () => {
        if (onClose) {
            onClose();
        } else {
            navigate('/dashboard?tab=gst&sub=documents');
        }
    };

    useEffect(() => {
        if (initialPersonId) {
            setFormData(prev => ({ ...prev, person_id: initialPersonId }));
        }
    }, [initialPersonId]);

    useEffect(() => {
        if (!isOpen) return;
        const original = document.body.style.overflow;
        document.body.style.overflow = 'hidden';
        return () => {
            document.body.style.overflow = original || 'unset';
        };
    }, [isOpen]);

    const handleChange = (e) => {
        const { name, value, type, checked, files } = e.target;

        if (type === 'file') {
            const file = files[0];
            if (file) {
                // Basic validation for preview
                const allowedTypes = ['application/pdf', 'image/jpeg', 'image/png'];
                if (!allowedTypes.includes(file.type)) {
                    setError('Unsupported file type. Allowed: PDF, JPG, PNG.');
                    setSelectedFile(null);
                    return;
                }
                if (file.size > 10 * 1024 * 1024) {
                    setError('File size exceeds 10MB limit.');
                    setSelectedFile(null);
                    return;
                }
                setError('');
                setSelectedFile(file);
            }
            return;
        }

        setFormData((prev) => ({
            ...prev,
            [name]: type === 'checkbox' ? checked : value,
        }));

        // Reset document type if person_id changes to trigger re-fetch
        if (name === 'person_id') {
            setFormData(prev => ({ ...prev, document_type: '' }));
            setRequiredDocs([]);
        }
    };

    // Effect to fetch required documents when person_id changes
    useEffect(() => {
        const fetchRequiredDocs = async () => {
            if (!formData.person_id || isNaN(formData.person_id)) {
                setRequiredDocs([]);
                return;
            }

            setFetchingDocs(true);
            setError('');
            try {
                // 1. Get the registration ID for this person
                const personRes = await api.get(`/api/v1/gst-people/dynamic_filter?person_id=${formData.person_id}`);
                const personData = personRes.data?.data?.[0];

                if (personData && personData.gst_registration_id) {
                    // 2. Get required documents for this registration and person
                    const docsRes = await api.get(`/api/v1/document-config/gst-registration/${personData.gst_registration_id}/required-documents?person_id=${formData.person_id}`);
                    const docs = docsRes.data?.documents || [];
                    setRequiredDocs(docs);
                    if (docs.length === 0) {
                        // If no specific required docs, maybe show all for this category?
                        // For now we just let it fall back to text, but we could fetch global list
                    }
                } else {
                    setRequiredDocs([]);
                    if (!personData) {
                        setError('No stakeholder found with this Person ID.');
                    } else if (!personData.gst_registration_id) {
                        setError('This person is not associated with any GST registration.');
                    }
                }
            } catch (err) {
                console.error("Failed to fetch required documents:", err);
                setError('Failed to fetch document types for this person.');
                setRequiredDocs([]);
            } finally {
                setFetchingDocs(false);
            }
        };

        const timer = setTimeout(fetchRequiredDocs, 500); // Debounce API calls
        return () => clearTimeout(timer);
    }, [formData.person_id]);

    const validateForm = () => {
        if (!formData.person_id) return "Person ID is required.";
        if (isNaN(formData.person_id) || Number(formData.person_id) <= 0) return "Person ID must be a positive number.";
        if (!formData.document_type || formData.document_type.length < 2) return "Document Type must be at least 2 characters.";

        if (uploadMethod === 'link') {
            if (!formData.document_url) return "Document URL is required.";
            try {
                new URL(formData.document_url);
            } catch (_) {
                return "Valid Document URL is required.";
            }
        } else {
            if (!selectedFile) return "Please select a file to upload.";
        }

        return null;
    };

    const handleSubmit = async (e) => {
        e.preventDefault();
        setError('');

        const validationError = validateForm();
        if (validationError) {
            setError(validationError);
            return;
        }

        setLoading(true);
        try {
            let finalUrl = formData.document_url;

            // Step 1: Upload file if method is 'file'
            if (uploadMethod === 'file') {
                const uploadFormData = new FormData();
                uploadFormData.append('file', selectedFile);

                const uploadRes = await api.post('/api/v1/gst-blob/upload', uploadFormData, {
                    headers: { 'Content-Type': 'multipart/form-data' }
                });
                finalUrl = uploadRes.data.blob_url;
            }

            // Step 2: Create document record
            const payload = {
                ...formData,
                person_id: parseInt(formData.person_id, 10),
                document_type: formData.document_type.trim().toUpperCase(),
                document_url: finalUrl.trim(),
            };

            await api.post(`/api/v1/gst-documents`, payload);

            setSuccess(true);
            setTimeout(() => {
                navigate('/dashboard?tab=gst&sub=documents');
            }, 2000);
        } catch (err) {
            setError(err.response?.data?.detail || err.message || 'Failed to upload document');
        } finally {
            setLoading(false);
        }
    };

    if (!isOpen) return null;


    return createPortal(
        <div className="gst-modal-overlay-v4 app-side-drawer-mode" onClick={handleClose}>
            <div className="gst-modal-card-v4 wide-modal app-drawer-panel gst-reg-side-drawer-shell" onClick={e => e.stopPropagation()}>
                <div className="modal-header-v4">
                    <div className="header-content-v4">
                        <div className="header-icon-box-v4" style={{ background: 'rgba(16, 185, 129, 0.1)', color: '#2eb87a' }}>
                            <Upload size={20} />
                        </div>
                        <div className="modal-title-box">
                            <div className="modal-header-texts">
                                <h2 className="modal-title-v4">
                                    {resolvedMode === 'details' ? 'Add Details' : 'Upload Document'}
                                    <span className="modal-header-tag-v4 create">NEW</span>
                                </h2>
                                <p className="modal-subtitle-v4">
                                    {resolvedMode === 'details' 
                                        ? 'Add document details for GST registrations' 
                                        : 'Upload GST registration documents'} • ID: {formData.person_id || '-'}
                                </p>
                            </div>
                        </div>
                    </div>
                    <button className="btn-drawer-close" onClick={handleClose}><X size={20} /></button>
                </div>

                <div className="modal-form-v4">
                    {success ? (
                        <div className="gst-modal-success-state">
                            <div className="gst-success-icon-wrapper">
                                <CheckCircle2 size={40} className="gst-success-tick" />
                            </div>
                            <h2 className="modal-title-v4">
                                Document Uploaded
                                <span className="modal-header-tag-v4 create">NEW</span>
                            </h2>
                            <p className="modal-subtitle-v4" style={{ textAlign: 'center' }}>The registration document has been successfully processed.</p>
                            <button className="glow-green" onClick={handleClose} style={{ marginTop: '32px' }}>
                                Go to Dashboard
                            </button>
                        </div>
                    ) : (
                        <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', flex: 1, minHeight: 0 }}>
                            <div className="form-scroll-container">
                                {error && (
                                    <div className="gst-message-banner error" style={{ marginBottom: '24px' }}>
                                        <AlertCircle size={18} />
                                        <span className="gst-message-banner-text">{error}</span>
                                    </div>
                                )}

                                <div className="form-section-group">
                                    <h3 className="section-title">1. Document Context</h3>
                                    <div className="form-grid-3" style={{ gridTemplateColumns: '1fr 2fr' }}>
                                        <div className="form-group-v4">
                                            <label className="modal-label-caps">Person ID*</label>
                                            <div className="modal-input-wrapper-v4">
                                                <Hash size={14} className="input-icon-v4" />
                                                <input
                                                    type="number"
                                                    name="person_id"
                                                    value={formData.person_id}
                                                    onChange={handleChange}
                                                    required
                                                    min="1"
                                                    className="modal-input-v4 with-icon"
                                                    placeholder="Enter ID"
                                                />
                                            </div>
                                        </div>

                                        <div className="form-group-v4">
                                            <label className="modal-label-caps">Document Type*</label>
                                            <div className="modal-input-wrapper-v4">
                                                <FileText size={14} className="input-icon-v4" />
                                                {requiredDocs.length > 0 ? (
                                                    <FormCustomSelect
                                                        name="document_type"
                                                        value={formData.document_type}
                                                        onChange={handleChange}
                                                        options={optionsFromConfig(
                                                            requiredDocs.map((doc) => ({
                                                                value: doc.value,
                                                                display_name: `${doc.display_name}${doc.is_mandatory ? ' *' : ''}`,
                                                            })),
                                                            'Select Type'
                                                        )}
                                                        placeholder={fetchingDocs ? 'Loading...' : 'Select Type'}
                                                        ariaLabel="Document type"
                                                        disabled={fetchingDocs}
                                                    />
                                                ) : (
                                                    <input
                                                        type="text"
                                                        name="document_type"
                                                        value={formData.document_type}
                                                        onChange={handleChange}
                                                        required
                                                        className="modal-input-v4 with-icon"
                                                        placeholder={fetchingDocs ? "Fetching..." : "e.g. PAN, Aadhaar"}
                                                        disabled={fetchingDocs}
                                                    />
                                                )}
                                                {fetchingDocs && (
                                                    <div className="input-loader-right">
                                                        <RotateCcw size={12} className="refresh-spin" />
                                                    </div>
                                                )}
                                            </div>
                                        </div>
                                    </div>
                                </div>

                                <div className="form-section-group" style={{ marginTop: '32px' }}>
                                    <h3 className="section-title">2. File Submission</h3>
                                    
                                    <div className="upload-method-selector-v4">
                                        <button
                                            type="button"
                                            className={`method-chip-v4 ${uploadMethod === 'file' ? 'active' : ''}`}
                                            onClick={() => setUploadMethod('file')}
                                        >
                                            <FileIcon size={14} /> Local File
                                        </button>
                                        <button
                                            type="button"
                                            className={`method-chip-v4 ${uploadMethod === 'link' ? 'active' : ''}`}
                                            onClick={() => setUploadMethod('link')}
                                        >
                                            <LinkIcon size={14} /> Direct Link
                                        </button>
                                    </div>

                                    <div className="submission-zone-v4">
                                        {uploadMethod === 'file' ? (
                                            <div className="premium-drop-zone-v4">
                                                {!selectedFile ? (
                                                    <label className="drop-zone-label-v4">
                                                        <input
                                                            type="file"
                                                            onChange={handleChange}
                                                            accept=".pdf,.jpg,.jpeg,.png"
                                                            className="hidden-file-input"
                                                        />
                                                        <div className="drop-zone-content-v4">
                                                            <div className="drop-icon-box-v4">
                                                                <Upload size={24} />
                                                            </div>
                                                            <div className="drop-text-box-v4">
                                                                <p className="main-drop-text">Click to browse or drag file here</p>
                                                                <p className="sub-drop-text">PDF, JPG, PNG • Max 10MB</p>
                                                            </div>
                                                        </div>
                                                    </label>
                                                ) : (
                                                    <div className="file-preview-card-v4">
                                                        <div className="file-preview-icon-v4">
                                                            <FileIcon size={20} />
                                                        </div>
                                                        <div className="file-preview-info-v4">
                                                            <span className="file-preview-name">{selectedFile.name}</span>
                                                            <span className="file-preview-size">{(selectedFile.size / 1024 / 1024).toFixed(2)} MB</span>
                                                        </div>
                                                        <button
                                                            type="button"
                                                            className="btn-remove-preview-v4"
                                                            onClick={() => setSelectedFile(null)}
                                                        >
                                                            <Trash2 size={16} />
                                                        </button>
                                                    </div>
                                                )}
                                            </div>
                                        ) : (
                                            <div className="premium-link-zone-v4">
                                                <div className="drop-icon-box-v4">
                                                    <LinkIcon size={24} />
                                                </div>
                                                <div className="drop-text-box-v4">
                                                    <p className="main-drop-text">Direct Document Link</p>
                                                    <textarea
                                                        name="document_url"
                                                        value={formData.document_url}
                                                        onChange={handleChange}
                                                        required
                                                        className="premium-link-textarea-v4"
                                                        placeholder="Paste your document URL here..."
                                                        rows="2"
                                                    />
                                                </div>
                                            </div>
                                        )}
                                    </div>

                                    <div className="verification-toggle-v4">
                                        <label className="v4-checkbox-label">
                                            <input
                                                type="checkbox"
                                                name="verified"
                                                checked={formData.verified}
                                                onChange={handleChange}
                                                className="modal-checkbox-v4"
                                            />
                                            <span className="checkbox-text-v4">Document verified by regulatory authority</span>
                                        </label>
                                    </div>
                                </div>
                            </div>

                            <div className="modal-footer-v4">
                                <div className="footer-actions-v4">
                                    <button
                                        type="button"
                                        className="gst-btn-secondary"
                                        onClick={handleClose}
                                    >
                                        Cancel
                                    </button>
                                    <button type="submit" className="glow-green" disabled={loading}>
                                        {loading ? <RotateCcw size={16} className="refresh-spin" /> : <Upload size={16} />}
                                        {loading ? 'Uploading...' : (resolvedMode === 'details' ? 'Save Details' : 'Upload Document')}
                                    </button>
                                </div>
                            </div>
                        </form>
                    )}
                </div>
            </div>
        </div>,
        document.body
    );
};

export default UploadDocuments;
