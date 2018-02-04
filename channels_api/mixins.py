from channels import Group
from django.core.paginator import Paginator
from rest_framework.exceptions import ValidationError

from .decorators import detail_action, list_action
from .settings import api_settings

class CreateModelMixin(object):
    """Mixin class that handles the creation of an object using a DRF serializer."""

    @list_action()
    def create(self, data, **kwargs):
        serializer = self.get_serializer(data=data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        return serializer.data, 201

    def perform_create(self, serializer):
        serializer.save()

class RetrieveModelMixin(object):

    @detail_action()
    def retrieve(self, pk, **kwargs):
        instance = self.get_object_or_404(pk)
        serializer = self.get_serializer(instance)
        return serializer.data, 200

#FIXME TEMP only
class ListModelMixin(object):

    @list_action()
    def list(self, data, **kwargs):

        if not data:
            data = {}

        raw_queryset = self.get_queryset()

        data_filter = self.get_filter(data.get('filter', ''),
                                      queryset=raw_queryset)


        if data_filter:
            queryset = self.filter_queryset(data_filter).qs
        else:
            queryset = raw_queryset

        if not queryset:
            return {'count': 0,
                    'num_pages': 0,
                    'objects': []}, 200

        paginator = Paginator(queryset, api_settings.DEFAULT_PAGE_SIZE)
        pagination_data = paginator.page(data.get('page', 1))

#FIXME include page value in list return

        serializer = self.get_serializer(pagination_data, many=True)

        if not pagination_data.has_next():
            next_page = None
        else:
            next_page = pagination_data.next_page_number()

        return_data = {
            'count': paginator.count,
            'num_pages': paginator.num_pages,
            'objects': serializer.data,
            'next_page': next_page
        }

        return return_data, 200


class UpdateModelMixin(object):

    @detail_action()
    def update(self, pk, data, **kwargs):
        instance = self.get_object_or_404(pk)
        serializer = self.get_serializer(instance, data=data)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return serializer.data, 200

    def perform_update(self, serializer):
        serializer.save()


class DeleteModelMixin(object):

    @detail_action()
    def delete(self, pk, **kwargs):
        instance = self.get_object_or_404(pk)
        self.perform_delete(instance)
        return dict(), 200

    def perform_delete(self, instance):
        instance.delete()

class SubscribeModelMixin(object):

    @detail_action()
    def subscribe(self, pk, data, **kwargs):

        if 'action' not in data:
            raise ValidationError('action required')
        action = data['action']
        group_name = self._group_name(action, id=pk)
        Group(group_name).add(self.message.reply_channel)
        return {'action': action}, 200


class SerializerMixin(object):
    """Mixin class that handles the loading of the serializer class, context and object."""

    serializer_class = None
    filter_class = None

    def get_filter(self, *args, **kwargs):
        filter_class = self.get_filter_class()
        if not filter_class:
            return None

        return filter_class(*args, **kwargs)

    def get_filter_class(self, *args, **kwargs):
        return self.filter_class

    def get_filter_context(self):
        return {}

    def get_serializer(self, *args, **kwargs):
        serializer_class = self.get_serializer_class()
        kwargs['context'] = self.get_serializer_context()
        return serializer_class(*args, **kwargs)

    def get_serializer_class(self):
        assert self.serializer_class is not None, (
            "'%s' should either include a `serializer_class` attribute, "
            "or override the `get_serializer_class()` method."
            % self.__class__.__name__
        )
        return self.serializer_class

    def get_serializer_context(self):
        return {
        }

    def serialize_data(self, instance):
        return self.get_serializer(instance).data
