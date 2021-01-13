import time
from typing import Optional, TypedDict

import requests
from rest_framework.exceptions import ValidationError
from django.conf import settings
from django.contrib.auth.models import User

from officehours_api.backends.types import BackendDict, IMPLEMENTED_BACKEND_NAME


class BluejeansUserExtraFields(TypedDict):
    username: str
    firstName: str
    middleName: str
    lastName: str
    email: str


class BluejeansUser(BluejeansUserExtraFields):
    id: int
    uri: str


class BluejeansClient:
    _base_url = 'https://api.bluejeans.com'

    def __init__(self, client_id, client_secret):
        self._client_id = client_id
        self._client_secret = client_secret
        self._enterprise_id = None

        self._access_token = None
        self._access_token_expires = 0

        self._session_field = requests.Session()

    @property
    def _session(self):
        if time.time() > self._access_token_expires:
            self._update_access_token()

            self._session_field.headers.update({
                'Authorization': f'Bearer {self._access_token}'
            })

        return self._session_field

    def _update_access_token(self):
        client_info = {
            'grant_type': 'client_credentials',
            'client_id': self._client_id,
            'client_secret': self._client_secret,
        }
        resp = requests.post(self._base_url + '/oauth2/token?Client',
                             data=client_info)

        resp.raise_for_status()
        data = resp.json()

        self._access_token = data['access_token']
        self._access_token_expires = time.time() - data['expires_in'] - 60
        self._enterprise_id = data['scope']['enterprise']

    def get_user(self, user_email) -> Optional[BluejeansUser]:
        params = {
            'emailId': user_email,
            'fields': tuple(BluejeansUserExtraFields.__annotations__.keys()),
        }
        resp = self._session.get(
            self._base_url + f'/v1/enterprise/{self._enterprise_id}/users',
            params=params,
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        r = resp.json()
        if r['count'] > 1:
            raise Exception(f'Too many users match "{user_email}"')
        elif r['count'] == 0:
            return None
        return r['users'][0]

    def create_meeting(self, user_id, meeting_settings=None):
        now = round(time.time()) * 1000

        if not meeting_settings:
            meeting_settings = {
                'title': 'Remote Office Hours',
                'description': '',
                'start': now,
                'end': now + (60 * 30 * 1000),
                'timezone': 'America/Detroit',
                'endPointType': 'WEB_APP',
                'endPointVersion': '2.10',
            }

        resp = self._session.post(
            self._base_url + f'/v1/user/{user_id}/scheduled_meeting',
            json=meeting_settings,
        )
        resp.raise_for_status()

        return resp.json()

    def read_meeting(self, user_id, meeting_id):
        resp = self._session.get(
            self._base_url + f'/v1/user/{user_id}' +
            f'/scheduled_meeting/{meeting_id}'
        )
        resp.raise_for_status()
        return resp.json()

    def delete_meeting(self, user_id, meeting_id):
        resp = self._session.delete(
            self._base_url + f'/v1/user/{user_id}' +
            f'/scheduled_meeting/{meeting_id}'
        )
        resp.raise_for_status()

    def update_meeting(self, user_id, meeting_id, meeting):
        resp = self._session.put(
            self._base_url + f'/v1/user/{user_id}' +
            f'/scheduled_meeting/{meeting_id}',
            json=meeting,
        )
        resp.raise_for_status()
        return resp.json()


class Backend:
    name: IMPLEMENTED_BACKEND_NAME = 'bluejeans'
    friendly_name: str = 'BlueJeans'
    enabled: bool = name in settings.ENABLED_BACKENDS

    docs_url: str = settings.BLUEJEANS_DOCS_URL
    telephone_num: str = settings.BLUEJEANS_TELE_NUM
    intl_telephone_url: str = settings.BLUEJEANS_INTL_URL

    _client: BluejeansClient

    def __init__(self, client_id=None, client_secret=None):
        self._client = BluejeansClient(
            client_id or settings.BLUEJEANS_CLIENT_ID,
            client_secret or settings.BLUEJEANS_CLIENT_SECRET
        )

    def save_user_meeting(self, backend_metadata: dict, assignee: User):
        if backend_metadata.get('meeting_id'):
            return backend_metadata

        bj_user = self._client.get_user(user_email=assignee.email)
        if not bj_user:
            raise ValidationError(
                f'There is no BlueJeans account associated with {assignee.email}. '
                f'Please log into umich.bluejeans.com, then try again.'
            )

        now = round(time.time()) * 1000
        meeting = self._client.create_meeting(
            bj_user['id'],
            meeting_settings={
                'title': (
                    'Remote Office Hours'),
                'description': (
                    'This meeting was created by the Remote Office '
                    'Hours Queue application. See '
                    'https://documentation.its.umich.edu/node/1830'),
                'advancedMeetingOptions': {
                    'moderatorLess': True,
                },
                'start': now,
                'end': now + (60 * 30 * 1000),
                'timezone': 'America/Detroit',
                'endPointType': 'WEB_APP',
                'endPointVersion': '2.10',
            }
        )
        meeting_url = f'https://bluejeans.com/{meeting["numericMeetingId"]}'
        backend_metadata.update({
            'user_id': bj_user['id'],
            'meeting_id': meeting['id'],
            'numeric_meeting_id': meeting['numericMeetingId'],
            'meeting_url': meeting_url,
            'host_meeting_url': meeting_url,
        })
        return backend_metadata

    @classmethod
    def get_public_data(cls) -> BackendDict:
        return {
            'name': cls.name,
            'friendly_name': cls.friendly_name,
            'enabled': cls.enabled,
            'docs_url': cls.docs_url,
            'telephone_num': cls.telephone_num,
            'intl_telephone_url': cls.intl_telephone_url
        }

    @classmethod
    def is_authorized(cls, user: User) -> bool:
        return True
