import unittest
from types import SimpleNamespace

import requests_mock

from canvasapi_async import Canvas
from canvasapi_async.enrollment_term import EnrollmentTerm
from canvasapi_async.paginated_list import PaginatedList
from canvasapi_async.user import User
from canvasapi_async.util import combine_kwargs
from tests import settings
from tests.util import register_uris


@requests_mock.Mocker()
class TestPaginatedList(unittest.TestCase):
    def setUp(self):
        self.canvas = Canvas(settings.BASE_URL, settings.API_KEY)
        self.requester = self.canvas._Canvas__requester

    # various length lists
    def test_paginated_list_empty(self, m):
        register_uris({"paginated_list": ["empty"]}, m)

        pag_list = PaginatedList(User, self.requester, "GET", "empty_list")
        item_list = [item for item in pag_list]
        self.assertEqual(len(item_list), 0)

    def test_paginated_list_single(self, m):
        register_uris({"paginated_list": ["single"]}, m)

        pag_list = PaginatedList(User, self.requester, "GET", "single_item")
        item_list = [item for item in pag_list]
        self.assertEqual(len(item_list), 1)
        self.assertIsInstance(item_list[0], User)

    def test_paginated_list_two_one_page(self, m):
        register_uris({"paginated_list": ["2_1_page"]}, m)

        pag_list = PaginatedList(User, self.requester, "GET", "two_objects_one_page")
        item_list = [item for item in pag_list]
        self.assertEqual(len(item_list), 2)
        self.assertIsInstance(item_list[0], User)

    def test_paginated_list_four_two_pages(self, m):
        register_uris({"paginated_list": ["4_2_pages_p1", "4_2_pages_p2"]}, m)

        pag_list = PaginatedList(
            User, self.requester, "GET", "four_objects_two_pages", per_page=2
        )
        item_list = [item for item in pag_list]
        self.assertEqual(len(item_list), 4)
        self.assertIsInstance(item_list[0], User)

    def test_paginated_list_six_three_pages(self, m):
        requires = {"paginated_list": ["6_3_pages_p1", "6_3_pages_p2", "6_3_pages_p3"]}
        register_uris(requires, m)

        pag_list = PaginatedList(
            User,
            self.requester,
            "GET",
            "six_objects_three_pages",
            _kwargs=combine_kwargs(per_page=2),
        )
        item_list = [item for item in pag_list]
        self.assertEqual(len(item_list), 6)
        self.assertIsInstance(item_list[0], User)

    # reusing iterator
    def test_iterator(self, m):
        requires = {"paginated_list": ["6_3_pages_p1", "6_3_pages_p2", "6_3_pages_p3"]}
        register_uris(requires, m)

        pag_list = PaginatedList(
            User,
            self.requester,
            "GET",
            "six_objects_three_pages",
            _kwargs=combine_kwargs(per_page=2),
        )
        list_1 = [item for item in pag_list]
        list_2 = [item for item in pag_list]
        self.assertEqual(list_1, list_2)

    # get item
    def test_getitem_first(self, m):
        requires = {"paginated_list": ["6_3_pages_p1", "6_3_pages_p2", "6_3_pages_p3"]}
        register_uris(requires, m)

        pag_list = PaginatedList(
            User,
            self.requester,
            "GET",
            "six_objects_three_pages",
            _kwargs=combine_kwargs(per_page=2),
        )
        first_item = pag_list[0]
        self.assertIsInstance(first_item, User)

    def test_getitem_second_page(self, m):
        requires = {"paginated_list": ["6_3_pages_p1", "6_3_pages_p2", "6_3_pages_p3"]}
        register_uris(requires, m)

        pag_list = PaginatedList(
            User,
            self.requester,
            "GET",
            "six_objects_three_pages",
            _kwargs=combine_kwargs(per_page=2),
        )
        third_item = pag_list[2]
        self.assertIsInstance(third_item, User)

    # slicing
    def test_slice_beginning(self, m):
        requires = {"paginated_list": ["6_3_pages_p1", "6_3_pages_p2", "6_3_pages_p3"]}
        register_uris(requires, m)

        pag_list = PaginatedList(
            User,
            self.requester,
            "GET",
            "six_objects_three_pages",
            _kwargs=combine_kwargs(per_page=2),
        )
        first_two_items = pag_list[:2]
        item_list = [item for item in first_two_items]
        self.assertEqual(len(item_list), 2)
        self.assertIsInstance(item_list[0], User)
        self.assertTrue(hasattr(item_list[0], "id"))
        self.assertEqual(item_list[0].id, "1")

    def test_slice_middle(self, m):
        requires = {"paginated_list": ["6_3_pages_p1", "6_3_pages_p2", "6_3_pages_p3"]}
        register_uris(requires, m)

        pag_list = PaginatedList(
            User,
            self.requester,
            "GET",
            "six_objects_three_pages",
            _kwargs=combine_kwargs(per_page=2),
        )
        middle_two_items = pag_list[2:4]
        item_list = [item for item in middle_two_items]
        self.assertEqual(len(item_list), 2)
        self.assertIsInstance(item_list[0], User)
        self.assertTrue(hasattr(item_list[0], "id"))
        self.assertEqual(item_list[0].id, "3")

    def test_slice_end(self, m):
        requires = {"paginated_list": ["6_3_pages_p1", "6_3_pages_p2", "6_3_pages_p3"]}
        register_uris(requires, m)

        pag_list = PaginatedList(
            User,
            self.requester,
            "GET",
            "six_objects_three_pages",
            _kwargs=combine_kwargs(per_page=2),
        )
        middle_two_items = pag_list[4:6]
        item_list = [item for item in middle_two_items]
        self.assertEqual(len(item_list), 2)
        self.assertIsInstance(item_list[0], User)
        self.assertTrue(hasattr(item_list[0], "id"))
        self.assertEqual(item_list[0].id, "5")

    def test_slice_oversize(self, m):
        requires = {"paginated_list": ["4_2_pages_p1", "4_2_pages_p2"]}
        register_uris(requires, m)

        pag_list = PaginatedList(
            User,
            self.requester,
            "GET",
            "four_objects_two_pages",
            _kwargs=combine_kwargs(per_page=2),
        )
        oversized_slice = pag_list[0:10]
        item_list = [item for item in oversized_slice]
        self.assertEqual(len(item_list), 4)

    def test_slice_out_of_bounds(self, m):
        requires = {"paginated_list": ["4_2_pages_p1", "4_2_pages_p2"]}
        register_uris(requires, m)

        pag_list = PaginatedList(
            User,
            self.requester,
            "GET",
            "four_objects_two_pages",
            _kwargs=combine_kwargs(per_page=2),
        )
        out_of_bounds = pag_list[4:5]
        item_list = [item for item in out_of_bounds]
        self.assertEqual(len(item_list), 0)

    # __repr__()
    def test_repr(self, m):
        requires = {"paginated_list": ["6_3_pages_p1", "6_3_pages_p2", "6_3_pages_p3"]}
        register_uris(requires, m)

        pag_list = PaginatedList(
            User,
            self.requester,
            "GET",
            "six_objects_three_pages",
            _kwargs=combine_kwargs(per_page=2),
        )
        self.assertEqual(pag_list.__repr__(), "<PaginatedList of type User>")

    def test_root_element_incorrect(self, m):
        register_uris({"account": ["get_enrollment_terms"]}, m)

        pag_list = PaginatedList(
            EnrollmentTerm, self.requester, "GET", "accounts/1/terms", _root="wrong"
        )

        with self.assertRaises(ValueError):
            pag_list[0]
            self.assertEqual(
                pag_list[0], "The key <wrong> does not exist in the response."
            )

    def test_root_element(self, m):
        register_uris({"account": ["get_enrollment_terms"]}, m)

        pag_list = PaginatedList(
            EnrollmentTerm,
            self.requester,
            "GET",
            "accounts/1/terms",
            _root="enrollment_terms",
        )

        self.assertIsInstance(pag_list[0], EnrollmentTerm)

    def test_negative_index(self, m):
        # Regression test for https://github.com/ucfopen/canvasapi/issues/305
        # Ensure that we can't use negative indexing, even after loading a page

        register_uris({"paginated_list": ["4_2_pages_p1", "4_2_pages_p2"]}, m)
        pag_list = PaginatedList(
            User,
            self.requester,
            "GET",
            "four_objects_two_pages",
            _kwargs=combine_kwargs(per_page=2),
        )
        pag_list[0]

        with self.assertRaises(IndexError):
            pag_list[-1]

    def test_negative_index_for_slice_start(self, m):
        # Regression test for https://github.com/ucfopen/canvasapi/issues/305
        # Ensure that we can't slice using a negative index as the start item

        register_uris({"paginated_list": ["4_2_pages_p1", "4_2_pages_p2"]}, m)
        pag_list = PaginatedList(
            User,
            self.requester,
            "GET",
            "four_objects_two_pages",
            _kwargs=combine_kwargs(per_page=2),
        )
        pag_list[0]

        with self.assertRaises(IndexError):
            pag_list[-1:1]

    def test_negative_index_for_slice_end(self, m):
        # Regression test for https://github.com/ucfopen/canvasapi/issues/305
        # Ensure that we can't slice using a negative index as the end item

        register_uris({"paginated_list": ["4_2_pages_p1", "4_2_pages_p2"]}, m)
        pag_list = PaginatedList(
            User,
            self.requester,
            "GET",
            "four_objects_two_pages",
            _kwargs=combine_kwargs(per_page=2),
        )
        pag_list[0]

        with self.assertRaises(IndexError):
            pag_list[:-1]

    def test_paginated_list_no_header(self, m):
        register_uris(
            {"paginated_list": ["no_header_4_2_pages_p1", "no_header_4_2_pages_p2"]}, m
        )

        pag_list = PaginatedList(
            User,
            self.requester,
            "GET",
            "no_header_four_objects_two_pages",
            _root="assessments",
            _kwargs=combine_kwargs(per_page=2),
        )

        self.assertIsInstance(pag_list, PaginatedList)
        self.assertEqual(len(list(pag_list)), 4)
        self.assertIsInstance(pag_list[0], User)

    def test_paginated_list_no_header_no_next(self, m):
        register_uris({"paginated_list": ["no_header_no_next_key"]}, m)

        pag_list = PaginatedList(
            User, self.requester, "GET", "no_header_no_next_key", _root="assessments"
        )

        self.assertIsInstance(pag_list, PaginatedList)
        self.assertEqual(len(list(pag_list)), 2)
        self.assertIsInstance(pag_list[0], User)

    def test_empty_next_url_ends_pagination(self, m):
        register_uris({"paginated_list": ["no_header_empty_next"]}, m)

        pag_list = PaginatedList(
            User, self.requester, "GET", "no_header_empty_next", _root="assessments"
        )

        self.assertEqual(len(list(pag_list)), 2)
        self.assertEqual(len(m.request_history), 1)

    # per_page
    def test_per_page_in_kwargs_is_not_overridden(self, m):
        register_uris({"paginated_list": ["4_2_pages_p1", "4_2_pages_p2"]}, m)

        pag_list = PaginatedList(
            User,
            self.requester,
            "GET",
            "four_objects_two_pages",
            _kwargs=combine_kwargs(per_page=2),
        )
        list(pag_list)

        self.assertEqual(m.request_history[0].qs["per_page"], ["2"])

    def test_per_page_defaults_to_100(self, m):
        register_uris({"paginated_list": ["single"]}, m)

        pag_list = PaginatedList(User, self.requester, "GET", "single_item")
        list(pag_list)

        self.assertEqual(m.request_history[0].qs["per_page"], ["100"])

    # _next_link_from()
    def test_next_link_from_link_header(self, m):
        pag_list = PaginatedList(User, self.requester, "GET", "single_item")
        response = SimpleNamespace(
            links={"next": {"url": "https://example.com/api/v1/x?page=2"}}
        )

        self.assertEqual(
            pag_list._next_link_from(response, []),
            "https://example.com/api/v1/x?page=2",
        )

    def test_next_link_from_meta_pagination(self, m):
        pag_list = PaginatedList(User, self.requester, "GET", "single_item")
        response = SimpleNamespace(links={})

        self.assertEqual(
            pag_list._next_link_from(response, {"meta": {"pagination": {"next": "u"}}}),
            "u",
        )

    def test_next_link_from_missing(self, m):
        pag_list = PaginatedList(User, self.requester, "GET", "single_item")
        response = SimpleNamespace(links={})

        self.assertIsNone(
            pag_list._next_link_from(response, {"meta": {"pagination": {"prev": "p"}}})
        )

    def test_next_link_from_null_meta_next(self, m):
        # A present-but-null `next` key ends pagination rather than reaching
        # the regex, which cannot take None.
        pag_list = PaginatedList(User, self.requester, "GET", "single_item")
        response = SimpleNamespace(links={})

        self.assertIsNone(
            pag_list._next_link_from(response, {"meta": {"pagination": {"next": None}}})
        )

    def test_next_link_from_empty_url_passes_it_through(self, m):
        # An empty URL comes back unchanged rather than as None, because the
        # link dict itself is truthy. Pagination stops at the caller's
        # `if next_url` guard, not here.
        pag_list = PaginatedList(User, self.requester, "GET", "single_item")
        response = SimpleNamespace(links={"next": {"url": ""}})

        self.assertEqual(pag_list._next_link_from(response, []), "")

    # _strip_base()
    def test_strip_base_api_url(self, m):
        pag_list = PaginatedList(User, self.requester, "GET", "single_item")

        self.assertEqual(
            pag_list._strip_base("https://example.com/api/v1/courses?page=2"),
            "courses?page=2",
        )

    def test_strip_base_new_quizzes_url(self, m):
        pag_list = PaginatedList(User, self.requester, "GET", "single_item")

        self.assertEqual(
            pag_list._strip_base("https://example.com/api/quiz/v1/q?page=2"),
            "q?page=2",
        )

    # _records_from()
    def test_records_from_skips_none_and_merges_extra_attribs(self, m):
        pag_list = PaginatedList(
            User,
            self.requester,
            "GET",
            "single_item",
            extra_attribs={"course_id": 1},
        )

        content = pag_list._records_from([{"id": 1}, None])

        self.assertEqual(len(content), 1)
        self.assertIsInstance(content[0], User)
        self.assertEqual(content[0].course_id, 1)

    def test_records_from_root_missing_raises(self, m):
        pag_list = PaginatedList(
            User, self.requester, "GET", "single_item", _root="wrong"
        )

        with self.assertRaises(ValueError):
            pag_list._records_from({"other": []})
