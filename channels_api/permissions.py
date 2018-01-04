

class BasePermission(object):

    def has_permission(self, user, action, pk):
        pass


class AllowAny(BasePermission):

    def has_permission(self, user, action, pk):
        return True


class IsAuthenticated(BasePermission):

    def has_permission(self, user, action, pk):
        return user.pk and user.is_authenticated

class IsAdmin(BasePermission):

    def has_permission(self, user, action, pk):

        import pdb; pdb.set_trace()

        return user.is_super

