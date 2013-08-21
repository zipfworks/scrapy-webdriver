import inspect
from collections import deque
from threading import Lock
import copy

from scrapy import log

from scrapy_webdriver.http import WebdriverRequest, WebdriverActionRequest
from selenium import webdriver


class WebdriverManager(object):
    """Manages the life cycle of a webdriver instance."""
    USER_AGENT_KEY = 'phantomjs.page.settings.userAgent'

    def __init__(self, settings):
        self._lock = Lock()
        self._count = 0
        self._browser = settings.get('WEBDRIVER_BROWSER', None)
        self._user_agent = settings.get('USER_AGENT', None)
        self._options = settings.get('WEBDRIVER_OPTIONS', dict())
        self._timeout = settings.get('WEBDRIVER_TIMEOUT', None)
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
            if self._timeout:
                self._webdriver.set_page_load_timeout(self._timeout)
        return self._webdriver

    def acquire(self, request):
        """Acquire lock for the request, or enqueue request upon failure."""
        assert isinstance(request, WebdriverRequest), \
            'Only a WebdriverRequest can use the webdriver instance.'
        self._count+=1
        log.msg("grabbing webdriver lock",level=log.INFO)
        self._lock.acquire(True)
        log.msg("got webdriver lock",level=log.INFO)

    def release(self):
        """Release the the webdriver instance's lock."""
        log.msg("releasing webdriver lock",level=log.INFO)
        self._lock.release()
        self._count-=1

    def cleanup(self):
        """Clean up when the scrapy engine stops."""
        if self._webdriver is not None:
            self._webdriver.quit()
            assert self._count!=0, 'Webdriver queue not empty at engine stop.'
