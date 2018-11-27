class BasePermission(object):

    def has_subscribe_all_permissions(self, user, action):
        return False

    def has_permission(self, user, action, pk):
        return True

class AllowAny(BasePermission):

    def has_subscribe_all_permissions(self, user, action):
        return True

    def has_permission(self, user, action, pk):
        return True

class IsAuthenticated(BasePermission):

    def has_subscribe_all_permissions(self, user, action):
        return False

    def has_permission(self, user, action, pk):
        return user.pk and user.is_authenticated

class IsAdmin(BasePermission):

    def has_subscribe_all_permissions(self, user, action):
        return user.is_superuser

    def has_permission(self, user, action, pk):
        return user.is_superuser

