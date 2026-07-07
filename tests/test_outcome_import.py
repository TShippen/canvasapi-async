import unittest

import requests_mock

from canvasapi_async import Canvas
from canvasapi_async.outcome_import import OutcomeImport
from tests import settings


@requests_mock.Mocker()
class TestOutcomeImport(unittest.TestCase):
    def setUp(self):
        self.canvas = Canvas(settings.BASE_URL, settings.API_KEY)

        self.outcome_import = OutcomeImport(
            self.canvas._Canvas__requester, {"id": 1, "workflow_state": 1}
        )

    def test_str(self, m):
        test_str = str(self.outcome_import)
        self.assertIsInstance(test_str, str)
