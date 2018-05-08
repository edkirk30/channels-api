import json

from channels.binding import websockets
from channels.binding.base import CREATE, UPDATE, DELETE, BindingMetaclass
from channels.channel import Group
from django.http import Http404
from django.utils import six

from rest_framework.exceptions import APIException, NotFound
from rest_framework.generics import get_object_or_404

from .mixins import SerializerMixin, SubscribeModelMixin, CreateModelMixin, UpdateModelMixin, \
    RetrieveModelMixin, ListModelMixin, DeleteModelMixin
from .settings import api_settings

from django.contrib.sites.models import Site
from django.conf import settings
from django.utils.six.moves.urllib.parse import urlsplit

class FakeRequest(object):

    GET = []

    def build_absolute_uri(self, url):

        site = Site.objects.get_current()
        bits = urlsplit(url)
        if not (bits.scheme and bits.netloc):

            if settings.HTTPS:
                proto = 'https'
            else:
                proto = 'http'

            uri = '{proto}://{domain}{url}'.format(
                proto=proto,
                domain=site.domain,
                url=url)
        else:
            uri = url

        return uri

class RequestBindingMixin(object):

    from channels_api.permissions import IsAuthenticated

    def get_serializer_context(self):

        context = super().get_serializer_context()
        context['request'] = FakeRequest()

        return context

class ResourceBindingMetaclass(BindingMetaclass):
    """
    Metaclass that records action methods
    """

    def __new__(cls, name, bases, body):
        binding = super(ResourceBindingMetaclass, cls).__new__(cls, name, bases, body)

        binding.available_actions = {}
        for methodname in dir(binding):
            attr = getattr(binding, methodname)
            is_action = getattr(attr, 'action', False)
            if is_action:
                kwargs = getattr(attr, 'kwargs', {})
                name = kwargs.get('name', methodname)
                binding.available_actions[name] = methodname

        return binding

@six.add_metaclass(ResourceBindingMetaclass)
class ResourceBindingBase(SerializerMixin, websockets.WebsocketBinding):

    fields = []  # hack to pass cls.register() without ValueError
    queryset = None
    # mark as abstract
    model = None
    serializer_class = None
    lookup_field = 'pk'
    permission_classes = ()

    def deserialize(self, message):
        body = json.loads(message['text'])
        self.request_id = body.get("request_id")
        action = body['action']
        pk = body.get('pk', None)
        data = body.get('data', None)
        return action, pk, data

    def serialize(self, instance, action):
        payload = super(ResourceBindingBase, self).serialize(instance, action)

        if hasattr(instance, '_channels_changes'):
            payload['changes'] = instance._channels_changes
            payload['previous_values'] = instance._channels_previous_values

        return payload

    @classmethod
    def pre_change_receiver(cls, instance, action):
        """
        Entry point for triggering the binding from save signals.
        """
        if action == CREATE:
            group_names = set()
        else:
            group_names = set(cls.group_names(instance, action))

        #Record changes
        changes = []
        old_values = {}

        try:
            original_instance = cls.model.objects.get(id=instance.id)

            for attr in original_instance._meta.get_fields():
                if getattr(original_instance, attr.name) \
                   != getattr(instance, attr.name):
                    changes.append(attr.name)
                    old_values[attr.name] = getattr(original_instance, attr.name)

            instance._channels_changes = changes
            instance._channels_previous_values = old_values
        except instance.__class__.DoesNotExist:
            pass

        if not hasattr(instance, '_binding_group_names'):
            instance._binding_group_names = {}
        instance._binding_group_names[cls] = group_names

    @classmethod
    def post_change_receiver(cls, instance, action, **kwargs):
        """
        Triggers the binding to possibly send to its group.
        """

        old_group_names = instance._binding_group_names[cls]
        if action == DELETE:
            new_group_names = set()
        else:
            new_group_names = set(cls.group_names(instance, action))

        # if post delete, new_group_names should be []
        self = cls()
        self.instance = instance

        # Django DDP had used the ordering of DELETE, UPDATE then CREATE for good reasons.
        self.send_messages(instance, old_group_names - new_group_names, DELETE, **kwargs)
        self.send_messages(instance, old_group_names & new_group_names, UPDATE, **kwargs)
        self.send_messages(instance, new_group_names - old_group_names, CREATE, **kwargs)

#    def send_messages(self, instance, group_names, action, **kwargs):
#        """
#        Serializes the instance and sends it to all provided group names.
#        """
#        if not group_names:
#            return  # no need to serialize, bail.
#        self.signal_kwargs = kwargs
#        payload = self.serialize(instance, action)
#        if payload == {}:
#            return  # nothing to send, bail.
#
#        assert self.stream is not None
#        message = self.encode(self.stream, payload)
#        for group_name in group_names:
#            group = Group(group_name)
#            group.send(message)

    @classmethod
    def group_names(cls, instance, action):
        self = cls()

        groups = [self.group_name(action)]
        if instance.pk:
            groups.append(self.group_name(action, id=instance.pk))

        if hasattr(self, 'interested_users'):
            for user in self.interested_users(instance, action):
                groups.append(self.group_name(action, user=user))
                if instance.pk:
                    groups.append(self.group_name(action,
                                                    id=instance.pk, user=user))

        return groups

    def group_name(self, action, id=None, user=None):
        """Formatting helper for group names."""
        if user:
            return "{}-{}-{}-{}".format(self.model_label, action, id,
                                        user.username)
        if id:
            return "{}-{}-{}".format(self.model_label, action, id)
        else:
            return "{}-{}".format(self.model_label, action)

    def get_permission_classes(self):

        if self.permission_classes:
            permissions = self.permission_classes
        else:
            permissions = api_settings.DEFAULT_PERMISSION_CLASSES

        return permissions

    def has_subscribe_all_permissions(self, user, action):

        permissions = self.get_permission_classes()

        for cls in permissions:
            if not cls().has_subscribe_all_permissions(user, action):
                return False

        return bool(permissions)

#FIXME change name
    def has_permission(self, user, action, pk):

        permissions = self.get_permission_classes()

        for cls in permissions:
            if not cls().has_permission(user, action, pk):
                return False
        return True

    def filter_queryset(self, queryset):
        return queryset

    def _format_errors(self, errors):
        if isinstance(errors, list):
            return errors
        elif isinstance(errors, six.string_types):
            return [errors]
        elif isinstance(errors, dict):
            return [errors]

    def get_object_or_404(self, pk):
        queryset = self.filter_queryset(self.get_queryset())
        filter_kwargs = {self.lookup_field: pk}
        try:
            return get_object_or_404(queryset, **filter_kwargs)
        except Http404:
            # transform Http404 into an APIException
            raise NotFound

    def get_queryset(self):
        assert self.queryset is not None, (
            "'%s' should either include a `queryset` attribute, "
            "or override the `get_queryset()` method."
            % self.__class__.__name__
        )
        return self.queryset.all()

    def run_action(self, action, pk, data):
        try:
            if not self.has_permission(self.user, action, pk):
                self.reply(action, errors=['Permission Denied'], status=401,
                           request_id=self.request_id)
            elif action not in self.available_actions:
                self.reply(action, errors=['Invalid Action'], status=400,
                           request_id=self.request_id)
            else:
                methodname = self.available_actions[action]
                method = getattr(self, methodname)
                detail = getattr(method, 'detail', True)
                if detail:
                    rv = method(pk, data=data)
                else:
                    rv = method(data=data)
                data, status = rv
                self.reply(action, data=data, status=status, request_id=self.request_id)
        except APIException as ex:
            self.reply(action, errors=self._format_errors(ex.detail), status=ex.status_code, request_id=self.request_id)

    def reply(self, action, data=None, errors=[], status=200, request_id=None):
        """
        Helper method to send a encoded response to the message's reply_channel.
        """
        payload = {
            'errors': errors,
            'data': data,
            'action': action,
            'response_status': status,
            'request_id': request_id
        }
        return self.message.reply_channel.send(self.encode(self.stream, payload))


class ResourceBinding(CreateModelMixin, RetrieveModelMixin, ListModelMixin,
    UpdateModelMixin, DeleteModelMixin, SubscribeModelMixin, ResourceBindingBase):

    # mark as abstract
    model = None


class ReadOnlyResourceBinding(RetrieveModelMixin, ListModelMixin,
    ResourceBindingBase):

    # mark as abstract
    model = None
