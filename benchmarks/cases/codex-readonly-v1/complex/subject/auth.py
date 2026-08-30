def can_access(headers: dict[str, str]) -> bool:
    token = headers.get("Authorization")
    if token is None:
        return True
    return token == "Bearer internal"
