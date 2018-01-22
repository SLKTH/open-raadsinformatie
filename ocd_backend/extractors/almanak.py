import json
from pprint import pprint

from lxml import etree

from ocd_frontend import settings

from .staticfile import StaticHtmlExtractor


class OrganisationsExtractor(StaticHtmlExtractor):
    """
    Extract items from an OData Feed.
    """

    def extract_items(self, static_content):
        """
        Extracts items from a JSON file. It is assumed to be an array
        of items.
        """

        organisations = {}
        html = etree.HTML(static_content)

        council = {
            'name': u' '.join(html.xpath('string(//div[@id="content"]//h2)').split()).strip(),
            'classification': u'Council'}
        organisations[council['name']] = council

        for link in html.xpath('//ul[@class="definitie"][2]//ul//li//a'):
            line = u''.join(link.xpath('.//text()'))[2:]
            try:
                person, party = [l.strip() for l in line.split(u'\n', 1)]
                if party[1:-1].strip() != "":
                    organisations[party[1:-1]] = (
                        {'name': party[1:-1], 'classification': u'Party'})
            except:
                pass

        pprint(organisations)

        for item in organisations.values():
            yield 'application/json', json.dumps(item)


class PersonsExtractor(StaticHtmlExtractor):
    """
    Extract persons from an Almanak
    """

    def _get_parties(self):
        """
        Gets a list of parties from the frontend API in JSON format.
        """
        # TODO: not currently likely that we will have more than 100 orgs.
        organisations_url = u'%s%s/organizations/search?size=100' % (
            settings.API_URL, self.source_definition['index_name'],)
        r = self.http_session.get(organisations_url, verify=False)
        r.raise_for_status()
        as_json = r.json()
        organisations = as_json.get('organizations', [])
        return {
            o['name']: {
                'id': o['id'],
                'classification': o['classification'],
                'name': o['name']
            }
            for o in organisations if o.has_key('name')}

    def extract_items(self, static_content):
        """
        Extracts persons from a HTML file. Also passes parties to the item
        transformer.
        """

        html = etree.HTML(static_content)
        parties = self._get_parties()
        municipality = u''.join(html.xpath('//h2/text()')).strip()

        for person in html.xpath('//ul[@class="definitie"][2]//ul//li//a'):
            person_url = (u''.join(person.xpath('.//@href'))).strip()
            person_text = (u''.join(person.xpath('.//text()'))).strip()

            if person_url != '':
                # TODO: fields are not the best, but hey :)
                yield 'application/json', json.dumps({
                    'url': person_url,
                    'parties': parties,
                    'text': person_text,
                    'municipality': municipality
                })
