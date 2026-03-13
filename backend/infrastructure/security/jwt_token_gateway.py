"""JWT token gateway adapter."""

from backend.utils.jwt_utils import get_jwt_manager


class JWTTokenGateway:
    def __init__(self, manager=None):
        self.manager = manager or get_jwt_manager()

    def __getattr__(self, item):
        return getattr(self.manager, item)

