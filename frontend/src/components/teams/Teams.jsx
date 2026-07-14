import React, { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import {
    Shield,
    Users,
    Plus,
    Edit2,
    Loader2,
    Users2,
    Briefcase,
    UserPlus,
    UserMinus,
    ExternalLink,
    PieChart,
    ChevronDown,
    ChevronRight,
    Search,
    X
} from 'lucide-react';
import api from '../../utils/api';
import './Teams.css';
import TeamModal from './TeamModal';
import ConfirmationModal from '../common/ConfirmationModal';
import Toast from '../common/Toast';

const Teams = ({ isAdmin }) => {
    const navigate = useNavigate();
    const [teams, setTeams] = useState([]);
    const [loading, setLoading] = useState(true);
    const [searchTerm, setSearchTerm] = useState('');
    const [expandedTeams, setExpandedTeams] = useState({});
    const [teamMembers, setTeamMembers] = useState({});
    const [membersLoading, setMembersLoading] = useState({});
    const [addingMember, setAddingMember] = useState({}); // { teamId: empId }

    const [selectedTeam, setSelectedTeam] = useState(null);
    const [isModalOpen, setIsModalOpen] = useState(false);

    // Member Search State
    const [memberSearchQuery, setMemberSearchQuery] = useState({});
    const [allEmployees, setAllEmployees] = useState([]);

    // Confirmation Modal State
    const [confirmModal, setConfirmModal] = useState({
        isOpen: false,
        title: '',
        message: '',
        onConfirm: null,
        loading: false
    });

    const [toast, setToast] = useState(null);

    const fetchTeams = useCallback(async () => {
        setLoading(true);
        try {
            const response = await api.get(`/app/v1/teams/teams?include_inactive=true`);
            setTeams(response.data.data || []);
        } catch (err) {
            console.error('Failed to fetch teams:', err);
        } finally {
            setLoading(false);
        }
    }, []);

    const fetchAllEmployees = useCallback(async () => {
        try {
            const response = await api.get(`/api/v1/employees/filter?is_active=true&limit=100`);
            setAllEmployees(response.data.data || response.data || []);
        } catch (err) {
            console.error('Failed to fetch all employees:', err);
        }
    }, []);

    useEffect(() => {
        fetchTeams();
        if (isAdmin) fetchAllEmployees();
    }, [fetchTeams, fetchAllEmployees, isAdmin]);

    const toggleTeamExpansion = async (teamId) => {
        const isCurrentlyExpanded = expandedTeams[teamId];
        setExpandedTeams(prev => ({ ...prev, [teamId]: !isCurrentlyExpanded }));

        if (!isCurrentlyExpanded && !teamMembers[teamId]) {
            setMembersLoading(prev => ({ ...prev, [teamId]: true }));
            try {
                // Fetch members for this team using the specialized team members endpoint
                const response = await api.get(`/app/v1/teams/${teamId}/members`);
                const members = response.data.members || [];
                setTeamMembers(prev => ({ ...prev, [teamId]: members }));
            } catch (err) {
                console.error('Failed to fetch team members:', err);
                setToast({ message: err.message || 'Failed to fetch team members', type: 'error' });
            } finally {
                setMembersLoading(prev => ({ ...prev, [teamId]: false }));
            }
        }
    };

    const handleAddMember = async (teamId, empId) => {
        if (addingMember[teamId]) return;

        setAddingMember(prev => ({ ...prev, [teamId]: empId }));
        try {
            await api.post(`/app/v1/teams/add-member?team_id=${teamId}&emp_id=${empId}`);

            // Show Success Toast
            setToast({ message: 'Member added to team successfully!', type: 'success' });

            // Refresh members and team count
            const response = await api.get(`/app/v1/teams/${teamId}/members`);
            const members = response.data.members || [];
            setTeamMembers(prev => ({ ...prev, [teamId]: members }));
            setMemberSearchQuery(prev => ({ ...prev, [teamId]: '' }));
            fetchTeams(); // To update member count in the main table
        } catch (err) {
            console.error('Failed to add member:', err);
            setToast({ message: err.message || 'Failed to add member to team', type: 'error' });
        } finally {
            setAddingMember(prev => ({ ...prev, [teamId]: null }));
        }
    };

    const handleRemoveMember = (teamId, empId) => {
        setConfirmModal({
            isOpen: true,
            title: 'Remove Member',
            message: 'Are you sure you want to remove this member from the team?',
            loading: false,
            onConfirm: async () => {
                setConfirmModal(prev => ({ ...prev, loading: true }));
                try {
                    await api.post(`/app/v1/teams/remove-member?team_id=${teamId}&emp_id=${empId}`);
                    // Refresh members and team count
                    const response = await api.get(`/app/v1/teams/${teamId}/members`);
                    const members = response.data.members || [];
                    setTeamMembers(prev => ({ ...prev, [teamId]: members }));
                    fetchTeams(); // To update member count
                    setConfirmModal(prev => ({ ...prev, isOpen: false }));
                    setToast({ message: 'Member removed from team successfully', type: 'success' });
                } catch (err) {
                    console.error('Failed to remove member:', err);
                    setToast({ message: err.message || 'Failed to remove member from team', type: 'error' });
                } finally {
                    setConfirmModal(prev => ({ ...prev, loading: false }));
                }
            }
        });
    };

    const handleViewProfile = (empId) => {
        if (empId) {
            navigate(`/dashboard?tab=employees&emp_id=${empId}`);
        }
    };

    const getRoleDistribution = (members = []) => {
        const dist = {};
        members.forEach(m => {
            dist[m.role] = (dist[m.role] || 0) + 1;
        });
        return Object.entries(dist).map(([role, count]) => `${count} ${role}${count > 1 ? 's' : ''}`).join(', ');
    };

    const filteredTeams = teams.filter(t =>
        (t.team_name || '').toLowerCase().includes(searchTerm.toLowerCase()) ||
        (t.team_code || '').toLowerCase().includes(searchTerm.toLowerCase())
    );

    const totalActiveMembers = teams.reduce((acc, t) => acc + (t.member_count || 0), 0);

    const handleCreateClick = () => {
        setSelectedTeam(null);
        setIsModalOpen(true);
    };

    const handleEditClick = (team, e) => {
        e.stopPropagation();
        setSelectedTeam(team);
        setIsModalOpen(true);
    };

    const TeamsSkeleton = () => (
        <div className="teams-container">
            <div className="teams-stats-row">
                {[...Array(3)].map((_, i) => (
                    <div key={i} className="teams-metric-card">
                        <div className="teams-icon-box" style={{ background: 'rgba(var(--fg-rgb),0.03)' }} />
                        <div className="teams-metric-info">
                            <div className="filings-ledger-skeleton-bar" style={{ width: '80px', marginBottom: '8px' }} />
                            <div className="filings-ledger-skeleton-bar" style={{ width: '40px', height: '24px' }} />
                        </div>
                    </div>
                ))}
            </div>

            <div className="teams-table-block">
                <div className="teams-table-header">
                    <div className="filings-ledger-skeleton-bar" style={{ width: '150px', height: '24px' }} />
                    <div className="filings-ledger-skeleton-bar" style={{ width: '200px', height: '32px' }} />
                </div>
                <div style={{ padding: '20px' }}>
                    {[...Array(6)].map((_, i) => (
                        <div key={i} style={{ display: 'flex', gap: '20px', padding: '16px 0', borderBottom: '1px solid var(--border-subtle)' }}>
                            <div className="filings-ledger-skeleton-bar" style={{ width: '20px' }} />
                            <div className="filings-ledger-skeleton-bar" style={{ width: '100px' }} />
                            <div className="filings-ledger-skeleton-bar" style={{ flex: 1 }} />
                            <div className="filings-ledger-skeleton-bar" style={{ width: '120px' }} />
                            <div className="filings-ledger-skeleton-bar" style={{ width: '80px' }} />
                        </div>
                    ))}
                </div>
            </div>
        </div>
    );

    if (loading) {
        return <TeamsSkeleton />;
    }

    return (
        <div className="teams-container">
            <div className="bg-orb orb-1"></div>

            {/* Metrics Row */}
            <div className="teams-stats-row">
                <div className="teams-metric-card">
                    <div className="teams-icon-box">
                        <Shield size={24} />
                    </div>
                    <div className="teams-metric-info">
                        <span className="label">Total Teams</span>
                        <span className="value">{teams.length}</span>
                    </div>
                </div>
                <div className="teams-metric-card">
                    <div className="teams-icon-box blue">
                        <Users size={24} />
                    </div>
                    <div className="teams-metric-info">
                        <span className="label">Active Members</span>
                        <span className="value">{totalActiveMembers}</span>
                    </div>
                </div>
                <div className="teams-metric-card">
                    <div className="teams-icon-box purple">
                        <Briefcase size={24} />
                    </div>
                    <div className="teams-metric-info">
                        <span className="label">Managed Departments</span>
                        <span className="value">{teams.length > 0 ? 'Admin' : 'None'}</span>
                    </div>
                </div>
            </div>

            {/* Teams Table Block */}
            <div className="teams-table-block">
                <div className="teams-table-header">
                    <div className="header-left">
                        <h3>Team Structure</h3>
                    </div>
                    <div className="header-right" style={{ display: 'flex', gap: '16px' }}>
                        <div className="topbar-search" style={{ width: '250px' }}>
                            <Search size={16} className="topbar-search-icon" />
                            <input
                                type="text"
                                placeholder="Search teams..."
                                value={searchTerm}
                                onChange={(e) => setSearchTerm(e.target.value)}
                            />
                        </div>
                        {isAdmin && (
                            <button className="btn-create-team" onClick={handleCreateClick}>
                                <Plus size={14} /> Create Team
                            </button>
                        )}
                    </div>
                </div>

                <table className="teams-table">
                    <thead>
                        <tr>
                            <th style={{ width: '40px' }}></th>
                            <th>Team Code</th>
                            <th>Team Name</th>
                            <th>Manager</th>
                            <th>Members</th>
                            <th style={{ width: '80px' }}>Actions</th>
                        </tr>
                    </thead>
                    <tbody>
                        {filteredTeams.map(team => (
                            <React.Fragment key={team.id}>
                                <tr>
                                    <td>
                                        <button
                                            className="btn-edit-team"
                                            style={{ background: 'transparent' }}
                                            onClick={() => toggleTeamExpansion(team.id)}
                                        >
                                            {expandedTeams[team.id] ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                                        </button>
                                    </td>
                                    <td>
                                        <span className="team-code-cell">{team.team_code}</span>
                                    </td>
                                    <td>
                                        <span className="team-name-cell">{team.team_name}</span>
                                    </td>
                                    <td>
                                        <div
                                            className="team-manager-badge"
                                            onClick={() => handleViewProfile(team.manager_emp_id)}
                                            style={{ cursor: team.manager_emp_id ? 'pointer' : 'default' }}
                                        >
                                            <div className="manager-avatar-mini">
                                                {team.manager_username?.charAt(0) || <Shield size={10} />}
                                            </div>
                                            <span>{team.manager_username || 'No Manager'}</span>
                                        </div>
                                    </td>
                                    <td>
                                        <span className="member-count-badge">
                                            {team.member_count || 0} Members
                                        </span>
                                    </td>
                                    <td>
                                        <div style={{ display: 'flex', gap: '8px' }}>
                                            <button className="btn-edit-team" title="Edit Team" onClick={(e) => handleEditClick(team, e)}>
                                                <Edit2 size={14} />
                                            </button>
                                        </div>
                                    </td>
                                </tr>
                                {expandedTeams[team.id] && (
                                    <tr>
                                        <td colSpan="6" className="team-members-expanded">
                                            {membersLoading[team.id] ? (
                                                <div style={{ display: 'flex', gap: '8px', alignItems: 'center', color: 'var(--text-muted)', fontSize: '13px' }}>
                                                    <Loader2 className="spin" size={14} /> Loading members...
                                                </div>
                                            ) : (
                                                <>
                                                    <div className="team-expanded-header">
                                                        <div className="analytics-pill">
                                                            <PieChart size={12} />
                                                            <span>{getRoleDistribution(teamMembers[team.id]) || 'No active members'}</span>
                                                        </div>
                                                        {isAdmin && (
                                                            <div className="add-member-search-container">
                                                                <div className="search-input-wrapper">
                                                                    <Search size={14} className="search-icon" />
                                                                    <input
                                                                        type="text"
                                                                        placeholder="Add employee..."
                                                                        value={memberSearchQuery[team.id] || ''}
                                                                        onChange={(e) => setMemberSearchQuery(prev => ({ ...prev, [team.id]: e.target.value }))}
                                                                    />
                                                                    {memberSearchQuery[team.id] && (
                                                                        <button className="clear-btn" onClick={() => setMemberSearchQuery(prev => ({ ...prev, [team.id]: '' }))}>
                                                                            <X size={12} />
                                                                        </button>
                                                                    )}
                                                                </div>
                                                                {memberSearchQuery[team.id] && (
                                                                    <div className="search-results-dropdown">
                                                                        {(() => {
                                                                            const query = (memberSearchQuery[team.id] || '').toLowerCase();
                                                                            const results = allEmployees
                                                                                .filter(emp => {
                                                                                    const username = (emp.username || '').toLowerCase();
                                                                                    const firstName = (emp.first_name || '').toLowerCase();
                                                                                    const lastName = (emp.last_name || '').toLowerCase();
                                                                                    const fullName = `${firstName} ${lastName}`.trim();
                                                                                    const empId = String(emp.emp_id || '');

                                                                                    return (
                                                                                        (username.includes(query) ||
                                                                                            firstName.includes(query) ||
                                                                                            lastName.includes(query) ||
                                                                                            fullName.includes(query) ||
                                                                                            empId.includes(query)) &&
                                                                                        !teamMembers[team.id]?.some(m => m.emp_id === emp.emp_id)
                                                                                    );
                                                                                })
                                                                                .slice(0, 8);

                                                                            if (results.length === 0) {
                                                                                return <div className="search-no-results">No eligible employees found</div>;
                                                                            }

                                                                            return results.map(emp => {
                                                                                const isAdding = addingMember[team.id] === emp.emp_id;
                                                                                return (
                                                                                    <div
                                                                                        key={emp.emp_id}
                                                                                        className={`search-result-item ${isAdding ? 'processing' : ''}`}
                                                                                        onClick={() => !isAdding && handleAddMember(team.id, emp.emp_id)}
                                                                                    >
                                                                                        <div className="manager-avatar-mini" style={{ width: '24px', height: '24px', fontSize: '10px' }}>
                                                                                            {(emp.username || '?').charAt(0)}
                                                                                        </div>
                                                                                        <div className="search-result-info">
                                                                                            <span className="username">{emp.username || 'Unknown'}</span>
                                                                                            <span className="emp-id">ID: {emp.emp_id} • {emp.role || 'Member'}</span>
                                                                                        </div>
                                                                                        {isAdding ? (
                                                                                            <Loader2 size={14} className="spin" style={{ marginLeft: 'auto', color: 'var(--info)' }} />
                                                                                        ) : (
                                                                                            <Plus size={14} style={{ marginLeft: 'auto', opacity: 0.5 }} />
                                                                                        )}
                                                                                    </div>
                                                                                );
                                                                            });
                                                                        })()}
                                                                    </div>
                                                                )}
                                                            </div>
                                                        )}
                                                    </div>

                                                    <div className="members-list">
                                                        {teamMembers[team.id]?.length > 0 ? (
                                                            teamMembers[team.id].map((member, idx) => (
                                                                <div key={member.emp_id} className="member-list-row interactive">
                                                                    <span className="member-index">{idx + 1}</span>
                                                                    <div className="member-avatar" style={{ background: 'rgba(var(--info-rgb), 0.15)', color: 'var(--info)' }}>
                                                                        {(member.username || '?').charAt(0).toUpperCase()}
                                                                    </div>
                                                                    <div className="member-list-info" onClick={() => handleViewProfile(member.emp_id)}>
                                                                        <span className="member-list-name">{member.username || 'Unknown'}</span>
                                                                    </div>
                                                                    <span className={`member-role-badge role-${(member.role || 'member').toLowerCase().replace(/\s+/g, '-')}`}>
                                                                        {member.role || 'Member'}
                                                                    </span>
                                                                    <span className="member-emp-id-badge">{member.emp_id}</span>
                                                                    <div className="member-list-actions">
                                                                        <button className="action-btn" title="View Profile" onClick={() => handleViewProfile(member.emp_id)}>
                                                                            <ExternalLink size={14} />
                                                                        </button>
                                                                        {isAdmin && (
                                                                            <button className="action-btn delete" title="Remove from Team" onClick={() => handleRemoveMember(team.id, member.emp_id)}>
                                                                                <UserMinus size={12} />
                                                                            </button>
                                                                        )}
                                                                    </div>
                                                                </div>
                                                            ))
                                                        ) : (
                                                            <div className="members-empty">No members assigned to this team.</div>
                                                        )}
                                                    </div>
                                                </>
                                            )}
                                        </td>
                                    </tr>
                                )}
                            </React.Fragment>
                        ))}
                        {filteredTeams.length === 0 && (
                            <tr>
                                <td colSpan="6" style={{ textAlign: 'center', padding: '40px', color: 'var(--text-muted)' }}>
                                    No teams found matching your search.
                                </td>
                            </tr>
                        )}
                    </tbody>
                </table>
            </div>

            <TeamModal
                isOpen={isModalOpen}
                onClose={() => setIsModalOpen(false)}
                onSave={fetchTeams}
                team={selectedTeam}
            />

            <ConfirmationModal
                isOpen={confirmModal.isOpen}
                onClose={() => setConfirmModal(prev => ({ ...prev, isOpen: false }))}
                onConfirm={confirmModal.onConfirm}
                title={confirmModal.title}
                message={confirmModal.message}
                loading={confirmModal.loading}
                type="danger"
            />

            {toast && (
                <Toast
                    message={toast.message}
                    type={toast.type}
                    onClose={() => setToast(null)}
                />
            )}
        </div>
    );
};

export default Teams;
