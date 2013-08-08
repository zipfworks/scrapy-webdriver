import signal

from scrapy import log
from scrapy.utils.decorator import inthread
from scrapy.utils.misc import load_object
from scrapy.exceptions import IgnoreRequest

from .http import WebdriverActionRequest, WebdriverRequest, WebdriverResponse

FALLBACK_HANDLER = 'scrapy.core.downloader.handlers.http.HttpDownloadHandler'

class WebdriverTimeout(Exception):
    pass

class WebdriverDownloadHandler(object):
    """This download handler uses webdriver, deferred in a thread.

    Falls back to the stock scrapy download handler for non-webdriver requests.

    """
    def __init__(self, settings):
        self._enabled = settings.get('WEBDRIVER_BROWSER') is not None
        self._timeout = settings.get('WEBDRIVER_TIMEOUT')
        self._fallback_handler = load_object(FALLBACK_HANDLER)(settings)

    def download_request(self, request, spider):
        """Return the result of the right download method for the request."""
        if self._enabled and isinstance(request, WebdriverRequest):

            # set the signal handler for the SIGALRM event
            def handler(signum, frame):

                # kill the selenium webdriver process (with SIGTERM,
                # so that it kills both the primary process and the
                # process that gets spawned)
                request.manager.webdriver.service.process.send_signal(signal.SIGTERM)

                # set the defunct _webdriver attribute back to
                # original value of None, so that the next time it is
                # accessed it is recreated.
                request.manager._webdriver = None

                # log an informative warning message
                msg = "'webdriver.get' for '%s' took more than %s seconds." % \
                    (request.url, self._timeout)
                spider.log(msg, level=log.WARNING)

            # bind the handler
            signal.signal(signal.SIGALRM, handler)

            if isinstance(request, WebdriverActionRequest):
                download = self._do_action_request
            else:
                download = self._download_request
        else:
            download = self._fallback_handler.download_request
        return download(request, spider)

    @inthread
    def _download_request(self, request, spider):
        """Download a request URL using webdriver."""
        log.msg('Downloading %s with webdriver' % request.url, level=log.DEBUG)

        # set a countdown timer for the webdriver.get
        if self._timeout:
            signal.alarm(self._timeout)

        # make the get request
        try:
            request.manager.webdriver.get(request.url)

        # if the get fails for any reason, set the webdriver attribute of the
        # response to the exception that occurred
        except Exception, exception:
            exception.page_source = '<html><head></head><body></body></html>'
            return WebdriverResponse(request.url, exception)

        # if the get finishes, defuse the bomb and return a response with the
        # webdriver attached
        else:
            if self._timeout:
                signal.alarm(0)
            return WebdriverResponse(request.url, request.manager.webdriver)
            
    @inthread
    def _do_action_request(self, request, spider):
        """Perform an action on a previously webdriver-loaded page."""
        log.msg('Running webdriver actions %s' % request.url, level=log.DEBUG)
        request.actions.perform()
        return WebdriverResponse(request.url, request.manager.webdriver)
