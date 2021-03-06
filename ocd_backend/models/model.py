# -*- coding: utf-8 -*-

import re

from ocd_backend import celery_app
from ocd_backend.models.database import Neo4jDatabase
from ocd_backend.models.definitions import Mapping, Prov, Ori
from ocd_backend.models.exceptions import MissingProperty, ValidationError, \
    QueryResultError
from ocd_backend.models.properties import PropertyBase, Property, \
    StringProperty, IntegerProperty, Relation
from ocd_backend.models.serializers import Neo4jSerializer
from ocd_backend.models.misc import Namespace, Uri
from ocd_backend.utils.misc import iterate, doc_type


class ModelMetaclass(type):
    database_class = Neo4jDatabase
    serializer_class = Neo4jSerializer

    def __new__(mcs, name, bases, attrs):
        # Collect fields from current class.
        definitions = dict()
        for key, value in list(attrs.items()):
            if isinstance(value, PropertyBase):
                definitions[key] = value
                attrs.pop(key)

        if len(bases) > 1 and not issubclass(bases[0], Namespace):
            raise ValueError('First argument of a Model subclass'
                             'should be a Namespace')

        new_class = super(ModelMetaclass, mcs).__new__(mcs, name, bases, attrs)

        # Walk through the MRO.
        for base in reversed(new_class.__mro__):
            # Collect fields from base class.
            if hasattr(base, '_definitions'):
                # noinspection PyProtectedMember
                definitions.update(base._definitions)

        new_class._definitions = definitions
        new_class.serializer = mcs.serializer_class()
        new_class.db = mcs.database_class(new_class.serializer)
        return new_class


class Model(object):
    __metaclass__ = ModelMetaclass

    # Top-level definitions
    ori_identifier = StringProperty(Mapping, 'ori/identifier')
    had_primary_source = StringProperty(Prov, 'hadPrimarySource')

    def absolute_uri(self):
        return '%s%s' % (self.uri, self.verbose_name())

    def compact_uri(self):
        return '%s:%s' % (self.prefix, self.verbose_name())

    def verbose_name(self):
        # if hasattr(cls, 'verbose_name'):
        #     return cls.verbose_name
        return type(self).__name__

    @classmethod
    def definitions(cls, props=True, rels=True):
        """ Return properties and relations objects from model definitions """
        props_list = list()
        for name, definition in cls._definitions.items():  # pylint: disable=no-member
            if (props and isinstance(definition, Property) or
                    (rels and isinstance(definition, Relation))):
                props_list.append((name, definition,))
        return props_list

    @classmethod
    def definition(cls, name):
        try:
            return cls._definitions[name]  # pylint: disable=no-member
        except KeyError:
            return

    @classmethod
    def inflate(cls, **deflated_props):
        instance = cls()
        for absolute_uri, value in deflated_props.items():
            definitions_mapping = {v.absolute_uri(): k for k, v in cls.definitions()}
            try:
                prop_name = definitions_mapping[absolute_uri]
                setattr(instance, prop_name, value)
            except KeyError:
                raise  # todo raise correct exception

        return instance

    def __init__(self, source_id=None, organization=None, source=None, source_id_key=None):
        # Set defaults
        #self.uri = None
        #self.prefix = None
        self.skip_validation = None
        # self.verbose_name = None
        self.values = dict()

        # https://argu.co/voc/mapping/<organization>/<source>/<source_id_key>/<source_id>
        # i.e. https://argu.co/voc/mapping/nl/ggm/vrsnummer/6655476
        if source_id:
            assert organization
            assert source
            assert source_id_key
            self.had_primary_source = Uri(Mapping, '{}/{}/{}/{}'.format(organization, source, source_id_key, source_id))
            self._source = source
        else:
            # Individuals also need a primary source or some queries will fail
            # As a solution the definition will be set as the primary source
            self.had_primary_source = self.absolute_uri()

    def __getattr__(self, item):
        try:
            return self.__dict__['values'][item]
        except KeyError:
            try:
                return self.__dict__[item]
            except KeyError:
                raise AttributeError(item)

    def __setattr__(self, key, value):
        definition = self.definition(key)

        # if key[0:1] != '_' and not definition:
        #     raise AttributeError("'%s' is not defined in %s" % (key, self.compact_uri()))

        if definition:
            value = definition.sanitize(value)
            self.values[key] = value
            return

        super(Model, self).__setattr__(key, value)

    def __contains__(self, item):
        try:
            if self.__getattribute__(item) is not None:
                return True
        except AttributeError:
            pass
        return False

    def __repr__(self):
        return '<%s Model>' % self.compact_uri()

    def get_ori_identifier(self):
        if not self.values.get('ori_identifier'):
            try:
                self.ori_identifier = self.db.get_identifier_by_source_id(
                    self,
                    self.had_primary_source,
                )
            except AttributeError:
                raise
            except MissingProperty:
                raise MissingProperty('OriIdentifier is not present, has the '
                                      'model been saved?')
        return self.ori_identifier

    def generate_ori_identifier(self):
        self.ori_identifier = Uri(Ori, celery_app.backend.increment("ori_identifier_autoincrement"))
        return self.ori_identifier

    def properties(self, props=True, rels=True):
        """ Returns namespaced properties with their inflated values """
        props_list = list()
        for name, prop in iterate({k: v for k, v in self.values.items() if k[0:1] != '_'}):
            definition = self.definition(name)
            if not definition:
                continue
            if (props and not isinstance(prop, Model)) or \
                    (rels and (isinstance(prop, Model) or isinstance(prop, Relationship))):
                props_list.append((self.serializer.uri_format(definition), prop,))  # pylint: disable=no-member
        return props_list

    def save(self):
        self.db.replace(self)  # pylint: disable=no-member

        # Recursive save
        for _, value in self.properties(rels=True, props=False):
            if isinstance(value, Model):
                value.save()

        self.attach_recursive()

        # Todo needs to be executed only once
        self.db.copy_relations()  # pylint: disable=no-member

    def attach_recursive(self):
        attach = list()
        for rel_type, other_object in self.properties(rels=True, props=False):
            attach.append(self.db.attach(self, other_object, rel_type))  # pylint: disable=no-member

            # End the recursive loop when self-referencing
            if self != other_object:
                attach.extend(other_object.attach_recursive())

        return attach


class Individual(Model):
    __metaclass__ = ModelMetaclass


class Relationship(object):
    """
    The Relationship model is used to explicitly specify one or more
    object model relations and describe what the relationship is about. The
    `rel` parameter is used to point to a object model that describes the
    relation, in a graph this is the edge between nodes. Note that not all
    serializers will make use of this.

    Relationship can have multiple arguments in order to specify multiple
    relations at once. Arguments of Relationship always relate to the property
    the Relationship is assigned to, and not to each other.

    ``
    # Basic way to assign relations
    object_model.parent = [a, b]

    # Relationship adds a way to describe the relation
    object_model.parent = Relationship(a, b, rel=c)

    # Under water this is translated to a list
    object_model.parent = [Relationship(a, rel=c), Relationship(b, rel=c)]
    ``
    """

    def __new__(cls, *args, **kwargs):
        if len(args) == 1:
            return super(Relationship, cls).__new__(cls)

        rel_list = list()
        for arg in args:
            rel_list.append(Relationship(arg, **kwargs))
        return rel_list

    def __init__(self, *args, **kwargs):
        self.model = args[0]
        self.rel = kwargs['rel']
