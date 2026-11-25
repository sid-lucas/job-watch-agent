"""A BrowserSession confined to one dedicated thread, callable from any thread.

The Playwright sync API only works in the thread that started it, while LangGraph's ToolNode
runs tools in worker threads. SessionThread starts the session in its own single thread and
queues every call to it: calls run there one at a time, in arrival order, and the caller
waits for the result (or the exception).
"""
from concurrent.futures import ThreadPoolExecutor

from job_watch.web.click_rules import Purpose
from job_watch.web.session import BrowserSession, ClickResult, Observation, TrailEvent


class SessionThread:
    """Same use as BrowserSession:

        with SessionThread(url) as session:
            observation = session.observe()     # from any thread
    """

    def __init__(self, start_url: str, **options):
        self._session = BrowserSession(start_url, **options)
        self._thread = ThreadPoolExecutor(max_workers=1, thread_name_prefix="browser")

    def __enter__(self) -> "SessionThread":
        try:
            self._run(self._session.__enter__)
        except BaseException:
            self._thread.shutdown()
            raise
        return self

    def __exit__(self, *exc_info) -> None:
        try:
            self._run(self._session.__exit__, None, None, None)
        finally:
            self._thread.shutdown()

    def observe(self) -> Observation:
        return self._run(self._session.observe)

    def click(self, element_id: int, purpose: Purpose) -> ClickResult:
        return self._run(self._session.click, element_id, purpose)

    @property
    def trail(self) -> list[TrailEvent]:
        return list(self._session.trail)

    def _run(self, function, *args):
        """Queue a call to the browser thread and wait for its result."""
        return self._thread.submit(function, *args).result()
