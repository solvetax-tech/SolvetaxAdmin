
async def get_user_permissions(emp_id: int, conn):
    """
    Fetch all permissions for a user based on their roles (direct and via groups).
    Returns a permissions dict suitable for JWT.

    Includes:
    - Error handling with logging
    - Basic permission validation (no empty or invalid permission codes)
    - Audit logging of permission fetch events
    """
    role_ids = set()
    try:
        # Direct employee-role assignments
        rows = await conn.fetch(f"""
            SELECT role_id FROM user_roles WHERE emp_id = $1
        """, emp_id)
        for row in rows:
            role_ids.add(row["role_id"])

        # Roles via group membership
        rows = await conn.fetch(f"""
            SELECT gr.role_id
            FROM group_members gm
            JOIN group_roles gr ON gm.group_id = gr.group_id
            WHERE gm.emp_id = $1
        """, emp_id)
        for row in rows:
            role_ids.add(row["role_id"])

        if not role_ids:
            logging.info(f"No roles found for emp_id={emp_id} at {datetime.datetime.utcnow().isoformat()}Z")
            return {"platform": {}}

        # Get all features/permissions for these roles
        rows = await conn.fetch(f"""
            SELECT f.feature_code, rf.permission_code
            FROM role_features rf
            JOIN features f ON rf.feature_id = f.id
            WHERE rf.role_id = ANY($1::int[])
        """, list(role_ids))

        permissions = {"platform": {}}
        for row in rows:
            feature = row["feature_code"]
            permission = row["permission_code"]

            # Basic validation: Skip invalid/empty permissions
            if not permission or not isinstance(permission, str):
                logging.warning(f"Invalid permission_code for emp_id={emp_id}, feature={feature}")
                continue

            if feature not in permissions["platform"]:
                permissions["platform"][feature] = set()
            permissions["platform"][feature].add(permission)

        # Convert permission sets to lists for serialization
        for feature in permissions["platform"]:
            permissions["platform"][feature] = list(permissions["platform"][feature])

        # Audit logging permission fetch
        logging.info(f"Permissions fetched for emp_id={emp_id} at {datetime.datetime.utcnow().isoformat()}Z: {permissions}")

        return permissions

    except PostgresError as e:
        logging.error(f"Database error while fetching permissions for emp_id={emp_id}: {e}")
        # You may want to raise or return an empty dict depending on your app's design
        return {"platform": {}}
    except Exception as e:
        logging.error(f"Unexpected error while fetching permissions for emp_id={emp_id}: {e}")
        return {"platform": {}}


