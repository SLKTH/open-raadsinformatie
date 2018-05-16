from datetime import datetime
import json
from pprint import pprint
from hashlib import sha1
from time import sleep
import re
import random

import iso8601

from ocd_backend.items.popolo import MotionItem, VotingEventItem
from ocd_backend.utils.misc import slugify
from ocd_backend import settings
from ocd_backend.extractors import HttpRequestMixin
from ocd_backend.utils.api import FrontendAPIMixin
from ocd_backend.utils.file_parsing import FileToTextMixin
from ocd_backend.utils.misc import (
    normalize_motion_id, full_normalized_motion_id)


class IBabsMotionVotingMixin(
        HttpRequestMixin, FrontendAPIMixin, FileToTextMixin):
    def _get_council(self):
        """
        Gets the organisation that represents the council.
        """

        results = self.api_request(
            self.source_definition['index_name'], 'organizations',
            classification='Council')
        return results[0]

    def _get_council_members(self):
        results = self.api_request(
            self.source_definition['index_name'], 'persons', size=500)
        return results

    def _get_council_parties(self):
        results = self.api_request(
            self.source_definition['index_name'], 'organizations',
            classification='Party', size=500)
        return results

    def _get_classification(self):
        return u'Moties'

    def _value(self, key):
        # pprint(self.source_definition['fields']['Moties'])
        try:
            actual_key = self.source_definition[
                'fields']['Moties']['Extra'][key]
        except KeyError:
            actual_key = key
        try:
            return self.original_item['_Extra']['Values'][actual_key]
        except KeyError:
            return None

    def _get_creator(self, creators_str, members, parties):
        # FIXME: currently only does the first. what do we do with the others?
        print "Creators: %s" % (creators_str)

        if creators_str is None:
            return

        creator_str = re.split(r'\)[,;]\s*', creators_str)[0]
        print "Looking for : %s" % (creator_str,)

        party_match = re.search(r' \(([^\)]*?)\)?$', creator_str)
        if not party_match:
            return

        print "Party match: %s, parties: %s" % (
            party_match.group(1),
            u','.join([p.get('name', u'') for p in parties]),)
        try:
            party = [p for p in parties if unicode(p.get('name', u'')).lower() == unicode(party_match.group(1)).lower()][0]
        except Exception as e:
            party = None

        if not party:
            return

        print "Found party: %s" % (party['name'])

        last_name_match = re.match(r'^([^\,]*)\, ', creator_str)
        if not last_name_match:
            return

        last_name_members = [m for m in members if last_name_match.group(1) in m['name']]
        if len(last_name_members) <= 0:
            return

        print "Found last name candidates: %s" % (u','.join([m['name'] for m in last_name_members]),)

        if len(last_name_members) == 1:
            print "Found final candidate base on last name: %s" % (last_name_members[0]['name'],)
            return last_name_members[0]

        for m in last_name_members:
            correct_party_affiliations = [ms for ms in m['memberships'] if ms['organization_id'] == party['id']]
            if len(correct_party_affiliations) > 0:
                print "Found final candidate base on last name and party: %s" % (m['name'],)
                return m

        return None

    def _find_legislative_session(self, motion_date, council, members, parties):
        # FIXME: match motions and ev ents when they're closest, not the first you run into
        motion_day_start = re.sub(r'T\d{2}:\d{2}:\d{2}', 'T00:00:00', motion_date.isoformat())
        motion_day_end = re.sub(r'T\d{2}:\d{2}:\d{2}', 'T23:59:59', motion_date.isoformat())
        #pprint((motion_date.isoformat(), motion_day_start, motion_day_end))
        try:
            results = self.api_request(
                self.source_definition['index_name'], 'events',
                classification=u'Agenda',
                start_date={
                    'from': motion_day_start, 'to': motion_day_end})
            # pprint(len(results))
            # filtered_results = [r for r in results if r['organization_id'] == council['id']]
            # return filtered_results[0]
            if results is not None:
                return results[0]
        except (KeyError, IndexError) as e:
            pprint("Error blaat")
        return None

    def _get_motion_id_encoded(self):
        return unicode(
            full_normalized_motion_id(self._value('Onderwerp')))

    def get_object_id(self):
        return self._get_motion_id_encoded()

    def get_original_object_id(self):
        return self._get_motion_id_encoded()

    def get_original_object_urls(self):
        # FIXME: what to do when there is not an original URL?
        return {"html": settings.IBABS_WSDL}

    def get_rights(self):
        return u'undefined'

    def get_collection(self):
        return unicode(self.source_definition['index_name'])

    def _get_motion_data(self, council, members, parties):
        combined_index_data = {}

        combined_index_data['id'] = unicode(self.get_original_object_id())

        combined_index_data['hidden'] = self.source_definition['hidden']

        combined_index_data['name'] = unicode(self._value('Onderwerp'))

        combined_index_data['identifier'] = combined_index_data['id']

        combined_index_data['organization_id'] = council['id']
        combined_index_data['organization'] = council

        # TODO: this gets only the first creator listed. We should fix it to
        # get all of them
        creator = self._get_creator(self._value('Indiener(s)'), members, parties)
        if creator is not None:
            combined_index_data['creator_id'] = creator['id']
            combined_index_data['creator'] = creator

        combined_index_data['classification'] = unicode(
            self.source_definition.get('classification', u'Moties'))

        combined_index_data['date'] = iso8601.parse_date(self.original_item['datum'][0],)
        # TODO: this is only for searching compatability ...
        combined_index_data['start_date'] = combined_index_data['date']
        combined_index_data['end_date'] = combined_index_data['date']

        # finding the event where this motion was put to a voting round
        legislative_session = self._find_legislative_session(
            combined_index_data['date'], council, members, parties)
        if legislative_session is not None:
            combined_index_data['legislative_session_id'] = legislative_session['id']
            combined_index_data['legislative_session'] = legislative_session

        combined_index_data['result'] = self._value('Status')
        combined_index_data['requirement'] = u'majority'
        combined_index_data['sources'] = []

        combined_index_data['vote_events'] = [self.get_original_object_id()]

        try:
            documents = self.original_item['_Extra']['Documents']
        except KeyError as e:
            documents = []
        if documents is None:
            documents = []

        # Default the text to "-". If a document contains actual text
        # then that text will be used.
        combined_index_data['text'] = u"-"
        for document in documents:
            sleep(1)
            print u"%s: %s" % (
                combined_index_data['name'], document['DisplayName'],)
            public_download_url = document['PublicDownloadURL']
            if not public_download_url.startswith('http'):
                public_download_url = u'https://www.mijnbabs.nl' + public_download_url
            description = self.file_get_contents(
                public_download_url,
                self.source_definition.get('pdf_max_pages', 20)).strip()
            combined_index_data['sources'].append({
                'url': public_download_url,
                'note': document['DisplayName'],
                'description': description
            })
            # FIXME: assumes that there is only one document from which
            # we can extract text; is that a valid assumption?
            if len(description) > 0:
                combined_index_data['text'] = description

        return combined_index_data

    def get_combined_index_data(self):
        council = self._get_council()
        members = self._get_council_members()
        parties = self._get_council_parties()

        return self._get_motion_data(council, members, parties)

    def get_index_data(self):
        return {}

    def get_all_text(self):
        text_items = []

        return u' '.join(text_items)


class IBabsMotionItem(IBabsMotionVotingMixin, MotionItem):
    pass


class IBabsVoteEventItem(IBabsMotionVotingMixin, VotingEventItem):
    def get_combined_index_data(self):
        combined_index_data = {}
        council = self._get_council()
        members = self._get_council_members()
        parties = self._get_council_parties()
        #pprint(parties)
        combined_index_data['motion'] = self._get_motion_data(
            council, members, parties)

        combined_index_data['classification'] = u'Stemmingen'
        combined_index_data['hidden'] = self.source_definition['hidden']
        combined_index_data['start_date'] = combined_index_data['motion']['date']
        combined_index_data['end_date'] = combined_index_data['motion']['date']

        # we can copy some fields from the motion
        for field in [
            'id', 'organization_id', 'organization', 'identifier', 'result',
            'sources', 'legislative_session_id'
        ]:
            try:
                combined_index_data[field] = combined_index_data['motion'][field]
            except KeyError as e:
                pass


        combined_index_data['counts'] = []
        combined_index_data['votes'] = []


        return combined_index_data
