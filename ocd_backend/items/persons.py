from lxml import etree

from ocd_backend.extractors import HttpRequestMixin
from ocd_backend.items import BaseItem
from ocd_backend.models import *
from ocd_backend.models.model import Relationship


class AlmanakPersonItem(HttpRequestMixin, BaseItem):
    def get_rights(self):
        return u'undefined'

    def get_collection(self):
        return unicode(self.source_definition['index_name'])

    def get_object_model(self):
        source_defaults = {
            'source': 'almanak',
            'source_id_key': 'identifier',
            'organization': self.source_definition['key'],
        }

        request_url = u'https://almanak.overheid.nl%s' % (
            unicode(self.original_item['url']),)

        r = self.http_session.get(request_url, verify=False)
        r.raise_for_status()
        html = etree.HTML(r.content)

        person = Person(self.original_item['id'], **source_defaults)
        person.name = html.xpath('string(//div[@id="content"]/h2/text())').strip()
        person.email = html.xpath('string(//a[starts-with(@href,"mailto:")]/text())').strip().split(' ')[0]
        person.gender = u'male' if person.name.startswith(u'Dhr. ') else u'female'

        municipality = Organization(self.source_definition['almanak_id'], **source_defaults)
        party = Organization(html.xpath('string(//ul[@class="definitie"]/li/ul/li)').strip(), **source_defaults)

        municipality_member = Membership()
        municipality_member.organization = municipality
        municipality_member.role = html.xpath('string(//div[@id="content"]//h3/text())').strip()

        party_member = Membership()
        party_member.organization = party
        party_member.role = 'Member'

        # person.member_of = [municipality_member, party_member]

        # person.member_of(municipality_member, party_member, rel=party)

        person.member_of = Relationship(municipality, rel=party)

        return person
