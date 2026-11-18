"""Who may do what. The only module that decides it."""
ROLES = {"admin": {"read", "write", "delete"}, "clerk": {"read", "write"}, "viewer": {"read"}}


def allowed(request, action):
    return action in ROLES.get(request.get("role"), set())
