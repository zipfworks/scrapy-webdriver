import copy
import inspect
from collections import deque
from threading import Lock
import copy

from scrapy.signals import engine_stopped
from scrapy_webdriver.http import WebdriverRequest, WebdriverActionRequest
from selenium import webdriver


class WebdriverManager(object):
    """Manages the life cycle of a webdriver instance."""
    USER_AGENT_KEY = 'phantomjs.page.settings.userAgent'

    def __init__(self, crawler):
        self.crawler = crawler
        self._lock = Lock()
        self._wait_queue = deque()
        self._wait_inpage_queue = deque()
        self._browser = crawler.settings.get('WEBDRIVER_BROWSER', None)
        self._implicit_wait = crawler.settings.get('WEBDRIVER_IMPLICIT_WAIT', 0)
        self._page_load_timeout = crawler.settings.get('WEBDRIVER_PAGE_LOAD_TIMEOUT', 0)
        self._script_timeout = crawler.settings.get('WEBDRIVER_SCRIPT_TIMEOUT', 0)
        self._user_agent = crawler.settings.get('USER_AGENT', None)
        self._options = crawler.settings.get('WEBDRIVER_OPTIONS', dict())
        self._timeout = crawler.settings.get('WEBDRIVER_TIMEOUT', None)
        self._webdriver = None
        if isinstance(self._browser, basestring):
            if '.' in self._browser:
                module, browser = self._browser.rsplit('.', 2)
            else:
                module, browser = 'selenium.webdriver', self._browser
            module = __import__(module, fromlist=[browser])
            self._browser = getattr(module, browser)
        elif inspect.isclass(self._browser):
            self._browser = self._browser
        else:
            self._webdriver = self._browser

    @property
    def _desired_capabilities(self):
        capabilities = dict()
        if self._user_agent is not None:
            capabilities[self.USER_AGENT_KEY] = self._user_agent
        return capabilities or None

    @property
    def webdriver(self):
        """Return the webdriver instance, instantiate it if necessary."""
        if self._webdriver is None:
            short_arg_classes = (webdriver.Firefox, webdriver.Ie)
            if issubclass(self._browser, short_arg_classes):
                cap_attr = 'capabilities'
            else:
                cap_attr = 'desired_capabilities'
            options = copy.deepcopy(self._options)
            options[cap_attr] = self._desired_capabilities
            self._webdriver = self._browser(**options)
            # Set the following timeout related settings on the webdriver:
            # * the amount of seconds to wait when an element cannot be found.
            # * the amount of seconds to wait for a page to load.
            # * the amount of seconds to wait for a script to execute.
            # For a more detailed explanation of these settings, please refer to
            # the Selenium documentation.
            self._webdriver.implicitly_wait(self._implicit_wait)
            self._webdriver.set_page_load_timeout(self._page_load_timeout)
            self._webdriver.set_script_timeout(self._script_timeout)
            self.crawler.signals.connect(self._cleanup, signal=engine_stopped)
            if self._timeout:
                self._webdriver.set_page_load_timeout(self._timeout)
        return self._webdriver

    def acquire(self, request):
        """Acquire lock for the request, or enqueue request upon failure."""
        assert isinstance(request, WebdriverRequest), \
            'Only a WebdriverRequest can use the webdriver instance.'
        if self._lock.acquire(False):
            request.manager = self
            return request
        else:
            if isinstance(request, WebdriverActionRequest):
                queue = self._wait_inpage_queue
            else:
                queue = self._wait_queue
            queue.append(request)

    def acquire_next(self):
        """Return the next waiting request, if any.

        In-page requests are returned first.

        """
        try:
            request = self._wait_inpage_queue.popleft()
        except IndexError:
            try:
                request = self._wait_queue.popleft()
            except IndexError:
                return
        return self.acquire(request)

    def release(self, msg):
        """Release the the webdriver instance's lock."""
        self._lock.release()

    def _cleanup(self):
        """Clean up when the scrapy engine stops."""
        if self._webdriver is not None:
            self._webdriver.quit()
            assert len(self._wait_queue) + len(self._wait_inpage_queue) == 0, \
                'Webdriver queue not empty at engine stop.'
