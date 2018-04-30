from datetime import datetime
import iso8601
from pprint import pprint

from ocd_backend.items import BaseItem
from ocd_backend.items.popolo import EventItem

from ocd_backend.extractors import HttpRequestMixin
from ocd_backend.utils.api import FrontendAPIMixin


class AttendanceForEventItem(HttpRequestMixin, FrontendAPIMixin, BaseItem):
    combined_index_fields = {
        'id': unicode,
        'hidden': bool,
        'doc': dict
    }

    def get_object_id(self):
        return unicode(self.original_item['id'])

    def get_original_object_id(self):
        return self.get_object_id()

    def get_original_object_urls(self):
        try:
            return self.original_item['meta']['original_object_urls']
        except KeyError as e:
            return {'html': self.original_item['html_url']}

    def get_rights(self):
        try:
            return self.original_item['meta']['rights']
        except KeyError as e:
            return u'undefined'

    def get_collection(self):
        return unicode(self.source_definition['index_name'])

    def _get_vote_event(self, event_id):
        try:
            results = self.api_request(
                self.source_definition['index_name'], 'vote_events',
                legislative_session_id=event_id, size=30)  # FIXME: for now, get the first
            print "vote events found:"
            for r in results:
                print "* %s (%s)" % (r['id'], u','.join(r.keys()),)
            return [r for r in results if r.has_key('votes')][0]
        except Exception as e:
            print "Got exception:", e
            pass

    def _get_voters(self, vote_event):
        if not vote_event.has_key('votes'):
            print "No votes found for event id %s (%s)!" % (self.original_item['id'], vote_event['id'],)
            return []

        print "Got votes"
        return [{'id': p['voter_id']} for p in vote_event['votes']]

    def get_object_model(self):
        combined_index_data = {}

        object_model['id'] = self.original_item['id']

        vote_event = self._get_vote_event(self.original_item['id'])
        if vote_event is None:
            print "No vote id found for event id %s!" % (self.original_item['id'],)
            return {}


        object_model['hidden'] = self.source_definition['hidden']
        object_model['doc'] = {
            'attendees': self._get_voters(vote_event)
        }

        return object_model

    def get_index_data(self):
        return {}

    def get_all_text(self):
        text_items = []

        return u' '.join(text_items)
