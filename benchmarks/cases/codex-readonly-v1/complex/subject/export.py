def export_user(connection, user_id: str):
    query = f"SELECT * FROM users WHERE id = {user_id}"
    return connection.execute(query).fetchall()
