import unittest
from types import SimpleNamespace

import anyio
import httpx
import pytest
import requests_mock
import respx

from canvasapi_async import Canvas, background_loop
from canvasapi_async.enrollment_term import EnrollmentTerm
from canvasapi_async.exceptions import CanvasException, Forbidden
from canvasapi_async.paginated_list import PaginatedList
from canvasapi_async.user import User
from canvasapi_async.util import combine_kwargs
from tests import settings, util
from tests.util import httpx_fixture_response, register_uris


def fetched_pages():
    """The page number of every request the httpx mock answered, in order."""
    return [int(call.request.url.params["page"]) for call in util.HTTPX_ROUTE.calls]


def serve_long_list(pages):
    """
    An httpx side effect answering a numbered list of single-record pages.

    Page one arrives through the requests mock; this covers everything after
    it, so a list long enough to watch the batches grow needs one fixture
    rather than one per page.
    """

    def respond(request):
        number = int(request.url.params["page"])
        if number > pages:
            return httpx.Response(200, json=[])

        headers = {}
        if number < pages:
            headers["Link"] = '<{}long_objects?page={}&per_page=1>; rel="next"'.format(
                settings.BASE_URL_WITH_VERSION, number + 1
            )

        return httpx.Response(200, headers=headers, json=[{"id": str(number)}])

    return respond


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

    def test_slice_open_end_loads_to_end(self, m):
        register_uris({"paginated_list": ["2_1_page"]}, m)

        pag_list = PaginatedList(User, self.requester, "GET", "two_objects_one_page")

        self.assertEqual([item.id for item in pag_list[1:]], ["2"])

    def test_open_slice_fetches_to_end(self, m):
        requires = {"paginated_list": ["6_3_pages_p1", "6_3_pages_p2", "6_3_pages_p3"]}
        register_uris(requires, m)

        pag_list = PaginatedList(
            User,
            self.requester,
            "GET",
            "six_objects_three_pages",
            _kwargs=combine_kwargs(per_page=2),
        )

        self.assertEqual([item.id for item in pag_list[2:]], ["3", "4", "5", "6"])
        # An open slice knows no end, so it reads ahead in batches the way
        # iteration does rather than a page at a time.
        self.assertEqual(sorted(fetched_pages()), [2, 3, 4, 5])

    def test_open_slice_after_iteration_requests_nothing(self, m):
        requires = {"paginated_list": ["6_3_pages_p1", "6_3_pages_p2", "6_3_pages_p3"]}
        register_uris(requires, m)

        pag_list = PaginatedList(
            User,
            self.requester,
            "GET",
            "six_objects_three_pages",
            _kwargs=combine_kwargs(per_page=2),
        )
        list(pag_list)
        already_fetched = util.HTTPX_ROUTE.call_count

        self.assertEqual([item.id for item in pag_list[2:]], ["3", "4", "5", "6"])
        self.assertEqual(util.HTTPX_ROUTE.call_count, already_fetched)

    def test_empty_slice_requests_nothing(self, m):
        register_uris({"paginated_list": ["6_3_pages_p1"]}, m)

        pag_list = PaginatedList(
            User,
            self.requester,
            "GET",
            "six_objects_three_pages",
            _kwargs=combine_kwargs(per_page=2),
        )

        self.assertEqual(list(pag_list[2:2]), [])
        self.assertEqual(len(m.request_history), 0)

    # concurrent fetching
    def test_six_three_pages_fetches_remaining_pages_concurrently(self, m):
        requires = {"paginated_list": ["6_3_pages_p1", "6_3_pages_p2", "6_3_pages_p3"]}
        register_uris(requires, m)

        in_flight = []
        peak = []

        async def watch(request):
            # respx records a call only once its side effect has returned, so
            # the overlap has to be counted from inside one.
            in_flight.append(request)
            peak.append(len(in_flight))
            await anyio.sleep(0.05)
            in_flight.pop()

            return httpx_fixture_response(request)

        util.HTTPX_ROUTE.mock(side_effect=watch)

        pag_list = PaginatedList(
            User,
            self.requester,
            "GET",
            "six_objects_three_pages",
            _kwargs=combine_kwargs(per_page=2),
        )
        item_list = [item.id for item in pag_list]

        self.assertEqual(item_list, ["1", "2", "3", "4", "5", "6"])
        self.assertEqual(sorted(fetched_pages()), [2, 3, 4, 5])
        self.assertGreaterEqual(max(peak), 2)

    def test_index_into_later_page_requests_pages_in_order(self, m):
        requires = {"paginated_list": ["6_3_pages_p1", "6_3_pages_p2", "6_3_pages_p3"]}
        register_uris(requires, m)

        pag_list = PaginatedList(
            User,
            self.requester,
            "GET",
            "six_objects_three_pages",
            _kwargs=combine_kwargs(per_page=2),
        )

        self.assertEqual(pag_list[4].id, "5")
        self.assertEqual(sorted(fetched_pages()), [2, 3])

    def test_no_next_link_is_last_page(self, m):
        requires = {"paginated_list": ["6_3_pages_p1", "6_3_pages_p2", "6_3_pages_p3"]}
        register_uris(requires, m)

        pag_list = PaginatedList(
            User,
            self.requester,
            "GET",
            "six_objects_three_pages",
            _kwargs=combine_kwargs(per_page=2),
        )
        pag_list[5]

        with self.assertRaises(IndexError):
            pag_list[6]

        self.assertEqual(sorted(fetched_pages()), [2, 3])

    def test_last_link_fixes_page_count(self, m):
        requires = {"paginated_list": ["last_link_p1", "last_link_p2", "last_link_p3"]}
        register_uris(requires, m)

        pag_list = PaginatedList(
            User,
            self.requester,
            "GET",
            "last_link_objects",
            _kwargs=combine_kwargs(per_page=2),
        )
        item_list = [item.id for item in pag_list]

        self.assertEqual(item_list, ["1", "2", "3", "4", "5", "6"])
        self.assertEqual(sorted(fetched_pages()), [2, 3])

    def test_last_link_on_an_empty_page_is_ignored(self, m):
        requires = {"paginated_list": ["empty_first_page_p1", "empty_first_page_p2"]}
        register_uris(requires, m)

        pag_list = PaginatedList(
            User,
            self.requester,
            "GET",
            "empty_first_page_objects",
            _kwargs=combine_kwargs(per_page=2),
        )

        self.assertEqual([item.id for item in pag_list], ["3", "4"])

    def test_page_size_corrected_from_short_first_page(self, m):
        requires = {"paginated_list": ["short_first_page_p1", "short_first_page_p2"]}
        register_uris(requires, m)

        pag_list = PaginatedList(
            User, self.requester, "GET", "short_first_page_objects", per_page=100
        )

        self.assertEqual(pag_list[3].id, "4")
        self.assertEqual(fetched_pages(), [2])

    def test_short_middle_page_does_not_shift_later_indices(self, m):
        requires = {
            "paginated_list": ["short_middle_p1", "short_middle_p2", "short_middle_p3"]
        }
        register_uris(requires, m)

        pag_list = PaginatedList(
            User, self.requester, "GET", "short_middle_objects", per_page=4
        )

        # Pages of four, two and four records. Indices count real records, so
        # the middle page being short moves nothing.
        self.assertEqual(pag_list[6].id, "7")
        self.assertEqual(pag_list[9].id, "10")

    def test_short_middle_page_iterates_in_order(self, m):
        requires = {
            "paginated_list": ["short_middle_p1", "short_middle_p2", "short_middle_p3"]
        }
        register_uris(requires, m)

        pag_list = PaginatedList(
            User, self.requester, "GET", "short_middle_objects", per_page=4
        )

        self.assertEqual(
            [item.id for item in pag_list], [str(number) for number in range(1, 11)]
        )

    def test_generated_page_current_link_mismatch_raises(self, m):
        requires = {
            "paginated_list": ["current_mismatch_p1", "current_mismatch_p2"],
        }
        register_uris(requires, m)

        pag_list = PaginatedList(
            User,
            self.requester,
            "GET",
            "current_mismatch_objects",
            _kwargs=combine_kwargs(per_page=2),
        )

        with self.assertRaises(CanvasException):
            list(pag_list)

    def test_failed_batch_raises_and_leaves_no_gap(self, m):
        register_uris({"paginated_list": ["forbidden_p1", "forbidden_p2"]}, m)

        pag_list = PaginatedList(
            User,
            self.requester,
            "GET",
            "forbidden_objects",
            _kwargs=combine_kwargs(per_page=2),
        )

        with self.assertRaises(Forbidden):
            list(pag_list)

        # The whole batch was dropped, so what is held is page one and
        # nothing after it.
        self.assertEqual([pag_list[0].id, pag_list[1].id], ["1", "2"])
        with self.assertRaises(Forbidden):
            pag_list[2]

    def test_retry_after_a_failed_batch_asks_for_it_again(self, m):
        register_uris({"paginated_list": ["forbidden_p1", "forbidden_p2"]}, m)

        pag_list = PaginatedList(
            User,
            self.requester,
            "GET",
            "forbidden_objects",
            _kwargs=combine_kwargs(per_page=2),
        )
        for _ in range(2):
            with self.assertRaises(Forbidden):
                list(pag_list)

        self.assertEqual(fetched_pages().count(2), 2)

    def test_page_one_after_a_failure_does_not_double_its_parameters(self, m):
        register_uris({"paginated_list": ["retry_p1_error"]}, m)

        pag_list = PaginatedList(
            User,
            self.requester,
            "GET",
            "retry_objects",
            _kwargs=combine_kwargs(per_page=2),
            active=True,
        )
        with self.assertRaises(CanvasException):
            pag_list[0]

        register_uris({"paginated_list": ["retry_p1"]}, m)
        pag_list[0]

        self.assertEqual(
            m.request_history[-1].qs, {"per_page": ["2"], "active": ["true"]}
        )

    # bookmark pagination
    def test_bookmark_next_link_stays_sequential(self, m):
        register_uris({"paginated_list": ["bookmark_p1", "bookmark_p2"]}, m)

        pag_list = PaginatedList(
            User,
            self.requester,
            "GET",
            "bookmark_objects",
            _kwargs=combine_kwargs(per_page=2),
        )
        item_list = [item.id for item in pag_list]

        self.assertEqual(item_list, ["1", "2", "3", "4"])
        self.assertEqual(util.HTTPX_ROUTE.call_count, 0)

    def test_bookmark_iteration_stops_requesting_when_the_caller_does(self, m):
        register_uris({"paginated_list": ["bookmark_p1", "bookmark_p2"]}, m)

        pag_list = PaginatedList(
            User,
            self.requester,
            "GET",
            "bookmark_objects",
            _kwargs=combine_kwargs(per_page=2),
        )
        for _ in pag_list:
            break

        self.assertEqual(len(m.request_history), 1)

    def test_bookmark_bounded_slice_stops_at_its_last_page(self, m):
        register_uris({"paginated_list": ["bookmark_p1", "bookmark_p2"]}, m)

        pag_list = PaginatedList(
            User,
            self.requester,
            "GET",
            "bookmark_objects",
            _kwargs=combine_kwargs(per_page=2),
        )

        self.assertEqual([item.id for item in pag_list[:2]], ["1", "2"])
        self.assertEqual(len(m.request_history), 1)

    # batches
    def test_stopping_at_the_first_record_costs_one_request(self, m):
        register_uris({"paginated_list": ["long_p1"]}, m)
        util.HTTPX_ROUTE.mock(side_effect=serve_long_list(40))

        pag_list = PaginatedList(
            User, self.requester, "GET", "long_objects", per_page=1
        )

        self.assertEqual(next(iter(pag_list)).id, "1")
        self.assertEqual(len(m.request_history), 1)
        self.assertEqual(util.HTTPX_ROUTE.call_count, 0)

    def test_reading_past_page_one_costs_one_batch(self, m):
        register_uris({"paginated_list": ["long_p1"]}, m)
        util.HTTPX_ROUTE.mock(side_effect=serve_long_list(40))

        pag_list = PaginatedList(
            User, self.requester, "GET", "long_objects", per_page=1
        )
        taken = []
        for item in pag_list:
            taken.append(item.id)
            if len(taken) == 2:
                break

        self.assertEqual(taken, ["1", "2"])
        self.assertEqual(sorted(fetched_pages()), [2, 3, 4, 5])

    def test_batches_double_up_to_the_ceiling(self, m):
        register_uris({"paginated_list": ["long_p1"]}, m)
        util.HTTPX_ROUTE.mock(side_effect=serve_long_list(40))

        pag_list = PaginatedList(
            User, self.requester, "GET", "long_objects", per_page=1
        )
        item_list = [item.id for item in pag_list]

        self.assertEqual(item_list, [str(number) for number in range(1, 41)])
        # Four rounds of 4, 8, 16 and 16 pages. The end is found in the fourth,
        # and nothing is asked for after it.
        pages = fetched_pages()
        self.assertEqual(sorted(pages[0:4]), list(range(2, 6)))
        self.assertEqual(sorted(pages[4:12]), list(range(6, 14)))
        self.assertEqual(sorted(pages[12:28]), list(range(14, 30)))
        self.assertEqual(sorted(pages[28:]), list(range(30, 46)))

    def test_odd_per_page_values_still_paginate(self, m):
        # Canvas applies its own limit whatever it is handed, and how many
        # records a page holds is read off page one, so nothing here is used
        # in arithmetic.
        register_uris({"paginated_list": ["odd_per_page_p1", "odd_per_page_p2"]}, m)

        for per_page in (0, -5, "many"):
            with self.subTest(per_page=per_page):
                pag_list = PaginatedList(
                    User,
                    self.requester,
                    "GET",
                    "odd_per_page_objects",
                    per_page=per_page,
                )

                self.assertEqual(pag_list[3].id, "4")
                self.assertEqual([item.id for item in pag_list], ["1", "2", "3", "4"])

    def test_empty_first_page_with_a_next_link_reaches_the_records_after_it(self, m):
        requires = {"paginated_list": ["empty_first_page_p1", "empty_first_page_p2"]}
        register_uris(requires, m)

        pag_list = PaginatedList(
            User,
            self.requester,
            "GET",
            "empty_first_page_objects",
            _kwargs=combine_kwargs(per_page=2),
        )

        self.assertEqual(pag_list[0].id, "3")

    def test_lists_that_never_paginate_start_no_event_loop(self, m):
        requires = {"paginated_list": ["empty", "single", "bookmark_p1", "bookmark_p2"]}
        register_uris(requires, m)

        for endpoint in ("empty_list", "single_item"):
            list(PaginatedList(User, self.requester, "GET", endpoint))
        list(
            PaginatedList(
                User,
                self.requester,
                "GET",
                "bookmark_objects",
                _kwargs=combine_kwargs(per_page=2),
            )
        )

        self.assertIsNone(background_loop._portal)

    def test_empty_page_ends_the_list(self, m):
        # The last page still carries a next link, and the page after it comes
        # back with no records at all, which is where the list ends.
        register_uris({"paginated_list": ["empty_end_p1", "empty_end_p2"]}, m)

        pag_list = PaginatedList(
            User,
            self.requester,
            "GET",
            "empty_end_objects",
            _kwargs=combine_kwargs(per_page=2),
        )

        self.assertEqual([item.id for item in pag_list], ["1", "2", "3", "4"])

    def test_bounded_slice_stops_at_a_known_last_page(self, m):
        requires = {"paginated_list": ["last_link_p1", "last_link_p2", "last_link_p3"]}
        register_uris(requires, m)

        pag_list = PaginatedList(
            User,
            self.requester,
            "GET",
            "last_link_objects",
            _kwargs=combine_kwargs(per_page=2),
        )

        self.assertEqual(len([item for item in pag_list[0:20]]), 6)
        self.assertEqual(sorted(fetched_pages()), [2, 3])

    def test_index_far_past_the_end_asks_for_no_more_than_a_full_batch(self, m):
        register_uris({"paginated_list": ["4_2_pages_p1", "4_2_pages_p2"]}, m)

        pag_list = PaginatedList(
            User,
            self.requester,
            "GET",
            "four_objects_two_pages",
            _kwargs=combine_kwargs(per_page=2),
        )

        with self.assertRaises(IndexError):
            pag_list[100]

        # The estimate wants fifty pages; an index batch is held to the same
        # ceiling iteration uses.
        self.assertEqual(sorted(fetched_pages()), list(range(2, 18)))

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
        # A root-bearing endpoint answers a page past its end with an empty
        # root rather than an empty array, so the rest of the batch that
        # reaches page two is registered alongside the two pages it holds.
        register_uris(
            {
                "paginated_list": [
                    "no_header_4_2_pages_p1",
                    "no_header_4_2_pages_p2",
                    "no_header_4_2_pages_past_end_p3",
                    "no_header_4_2_pages_past_end_p4",
                    "no_header_4_2_pages_past_end_p5",
                ]
            },
            m,
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

    def test_strip_base_foreign_url_raises(self, m):
        # A next link on some other host has nothing to strip, which is why a
        # link is stripped before the list stores anything about it.
        pag_list = PaginatedList(User, self.requester, "GET", "single_item")

        with self.assertRaises(AttributeError):
            pag_list._strip_base("https://elsewhere.example/api/v1/courses?page=2")

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


# httpx_fixture_response(), which every concurrently fetched page is answered
# from. Written as plain functions, since an async test method on a TestCase
# would never run and these share nothing with the class above.
def register_page_one():
    """Register the first page of the six-object fixture with both mockers."""
    with requests_mock.Mocker() as mocker:
        register_uris({"paginated_list": ["6_3_pages_p1"]}, mocker)


def request_for(page=None):
    """A GET for the six-object endpoint, optionally naming a page."""
    url = settings.BASE_URL_WITH_VERSION + "six_objects_three_pages?per_page=2"
    if page is not None:
        url = "{}&page={}".format(url, page)

    return httpx.Request("GET", url)


def test_httpx_fixture_answers_the_page_it_was_registered_for():
    register_page_one()

    response = httpx_fixture_response(request_for())

    assert [record["id"] for record in response.json()] == ["1", "2"]


def test_httpx_fixture_does_not_answer_another_page():
    register_page_one()

    response = httpx_fixture_response(request_for(page=7))

    assert response.json() == []
    assert "Link" not in response.headers


def test_httpx_fixture_answers_an_unregistered_path_with_an_empty_page():
    response = httpx_fixture_response(
        httpx.Request("GET", settings.BASE_URL_WITH_VERSION + "nothing_registered")
    )

    assert response.status_code == 200
    assert response.json() == []


def test_httpx_fixture_ignores_a_fixture_registered_for_another_method():
    util.HTTPX_FIXTURES.append(
        ("POST", settings.BASE_URL_WITH_VERSION + "courses", 201, {}, [{"id": "1"}])
    )

    assert (
        httpx_fixture_response(
            httpx.Request("GET", settings.BASE_URL_WITH_VERSION + "courses")
        ).json()
        == []
    )


def test_httpx_fixture_answers_from_the_last_matching_entry():
    for identifier in ("1", "2"):
        util.HTTPX_FIXTURES.append(
            (
                requests_mock.ANY,
                settings.BASE_URL_WITH_VERSION + "courses",
                200,
                {},
                [{"id": identifier}],
            )
        )

    response = httpx_fixture_response(
        httpx.Request("GET", settings.BASE_URL_WITH_VERSION + "courses")
    )

    assert [record["id"] for record in response.json()] == ["2"]


@pytest.mark.asyncio
async def test_respx_side_effect_returning_none_leaves_the_route_unmatched():
    """Pin the respx behaviour the suite's own httpx router relies on."""
    with respx.mock(assert_all_called=False) as outer:
        outer.route().mock(side_effect=lambda request: None)
        with respx.mock(base_url=settings.BASE_URL_WITH_VERSION) as inner:
            route = inner.get("courses").mock(return_value=httpx.Response(200, json=[]))
            async with httpx.AsyncClient() as client:
                await client.get(settings.BASE_URL_WITH_VERSION + "courses")

    assert route.call_count == 1
    assert outer.calls.call_count == 0
