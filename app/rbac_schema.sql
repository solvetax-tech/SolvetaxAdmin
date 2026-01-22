-- Enhanced Roles table with timestamps in solvetax schema
CREATE TABLE solvetax.roles (
  id SERIAL PRIMARY KEY,
  name VARCHAR(50) UNIQUE NOT NULL,
  description TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Enhanced Permissions table with category and timestamps in solvetax schema
CREATE TABLE solvetax.permissions (
  id SERIAL PRIMARY KEY,
  feature_code VARCHAR(100) UNIQUE NOT NULL,
  description TEXT,
  category VARCHAR(50),
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Role to Permission many-to-many mapping with audit columns in solvetax schema
CREATE TABLE solvetax.role_permissions (
  id SERIAL PRIMARY KEY,
  role_id INT REFERENCES solvetax.roles(id) ON DELETE CASCADE,
  permission_id INT REFERENCES solvetax.permissions(id) ON DELETE CASCADE,
  granted_by_emp_id INT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  UNIQUE (role_id, permission_id)
);

-- Employee to Role many-to-many mapping with assignment metadata in solvetax schema
CREATE TABLE solvetax.employee_roles (
  id SERIAL PRIMARY KEY,
  emp_id INT REFERENCES solvetax.employees(emp_id),
  role_id INT REFERENCES solvetax.roles(id),
  assigned_by_emp_id INT,
  assigned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(emp_id, role_id)
);

-- Group table to manage user groups
CREATE TABLE solvetax.groups (
  id SERIAL PRIMARY KEY,
  name VARCHAR(100) UNIQUE NOT NULL,
  description TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Group membership for employees
CREATE TABLE solvetax.group_members (
  id SERIAL PRIMARY KEY,
  group_id INT REFERENCES solvetax.groups(id) ON DELETE CASCADE,
  emp_id INT REFERENCES solvetax.employees(emp_id) ON DELETE CASCADE,
  joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(group_id, emp_id)
);

-- Role assignments to groups (for group-based role assignments)
CREATE TABLE solvetax.role_assignments (
  id SERIAL PRIMARY KEY,
  group_id INT REFERENCES solvetax.groups(id) ON DELETE CASCADE,
  role_id INT REFERENCES solvetax.roles(id),
  assigned_by_emp_id INT,
  assigned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(group_id, role_id)
);

-- Enhanced role audit log for tracking role changes in solvetax schema
CREATE TABLE solvetax.role_audit_log (
  id SERIAL PRIMARY KEY,
  emp_id INT NOT NULL,
  role_id INT NOT NULL,
  action VARCHAR(50) NOT NULL,
  performed_by_emp_id INT,
  ip_address VARCHAR(45),
  timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Seed roles
INSERT INTO solvetax.roles (name, description) VALUES
('admin', 'Administrator with full access'),
('sales_executive', 'Sales team member with limited access'),
('operations', 'Operations team with moderate access'),
('viewer', 'Read-only access to reports');

-- Seed permissions
INSERT INTO solvetax.permissions (feature_code, description, category) VALUES
('create_ticket', 'Ability to create new tickets', 'tickets'),
('read_ticket', 'View and read tickets', 'tickets'),
('approve_ticket', 'Can approve tickets', 'tickets'),
('assign_ticket', 'Assign tickets to users or teams', 'tickets'),
('close_ticket', 'Close or resolve tickets', 'tickets'),
('view_reports', 'View detailed reports', 'reports'),
('export_data', 'Export data to external files', 'reports'),
('import_data', 'Import data from external sources', 'system'),
('edit_user', 'Edit user profiles', 'users'),
('manage_users', 'Create and manage user accounts', 'users'),
('manage_roles', 'Create and manage roles and permissions', 'users'),
('delete_data', 'Delete sensitive or permanent data', 'system'),
('audit_logs_view', 'View audit and activity logs', 'system'),
('system_configuration', 'Modify system settings and configuration', 'system'),
('access_financial_reports', 'Access financial or billing reports', 'reports'),
('access_sensitive_data', 'View sensitive information', 'system'),
('reset_password', 'Reset passwords for users', 'users'),
('manage_groups', 'Create and manage user groups', 'users'),
('send_notifications', 'Send system-wide notifications', 'system');
