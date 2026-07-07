import unittest

import requests_mock

from canvasapi_async import Canvas
from canvasapi_async.scope import Scope
from tests import settings


@requests_mock.Mocker()
class TestGradingPeriod(unittest.TestCase):
    def setUp(self):
        self.canvas = Canvas(settings.BASE_URL, settings.API_KEY)

        self.scope = Scope(
            self.canvas._Canvas__requester, {"resource": "users", "verb": "PUT"}
        )

    def test_str(self, m):
        test_str = str(self.scope)
        self.assertIsInstance(test_str, str)
