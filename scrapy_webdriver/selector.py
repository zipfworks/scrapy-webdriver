import re

from scrapy.selector import Selector, SelectorList

_UNSUPPORTED_XPATH_ENDING = re.compile(r'.*/((@)?([^/()]+)(\(\))?)$')
_UNSUPPORTED_CSS_ENDING = re.compile(r'.*(::text|::attr\(([\w-]+)\))$')


class WebdriverXPathSelector(Selector):
    """Scrapy selector that works using XPath selectors in a remote browser.

    Based on some code from Marconi Moreto:
        https://github.com/marconi/ghost-selector

    """
    def __init__(self, response=None, webdriver=None, element=None,
                 *args, **kwargs):
        kwargs['response'] = response
        super(WebdriverXPathSelector, self).__init__(*args, **kwargs)
        self.response = response
        self.webdriver = webdriver or response.webdriver
        self.element = element

    def _make_result(self, result):
        if type(result) is not list:
            result = [result]
        return [self.__class__(webdriver=self.webdriver, element=e)
                for e in result]

    def css(self, css):
        """Return elements using the webdriver `find_elements_by_css` method.
        This adds support for useful css psuedo-selectors:
          - a.clicky::attr(href)
          - h2.heading::text
        """
        elem = self.element if self.element else self.webdriver
        ending = _UNSUPPORTED_CSS_ENDING.match(css)
        if ending:
            psuedo, attr = ending.groups()
            css = css[:-len(psuedo)]
        result = self._make_result(elem.find_elements_by_css_selector(css))
        if ending:
            if psuedo == '::text':
                result = (_TextNode(self.webdriver, r.element) for r in result)
            elif attr:
                result = (_NodeAttribute(r.element, attr) for r in result)
        return SelectorList(result)

    def xpath(self, xpath):
        """Return elements using the webdriver `find_elements_by_xpath` method.

        Some XPath features are not supported by the webdriver implementation.
        Namely, selecting text content or attributes:
          - /some/element/text()
          - /some/element/@attribute

        This function offers workarounds for both, so it should be safe to use
        them as you would with HtmlXPathSelector for simple content extraction.

        """
        xpathev = self.element if self.element else self.webdriver
        ending = _UNSUPPORTED_XPATH_ENDING.match(xpath)
        atsign = parens = None
        if ending:
            match, atsign, name, parens = ending.groups()
            if atsign:
                xpath = xpath[:-len(name) - 2]
            elif parens and name == 'text':
                xpath = xpath[:-len(name) - 3]
                # do the right thing for /some/div//text()
                if xpath.endswith('/'):
                    xpath = xpath+'/*'
        result = self._make_result(xpathev.find_elements_by_xpath(xpath))
        if atsign:
            result = (_NodeAttribute(r.element, name) for r in result)
        elif parens and result and name == 'text':
            result = (_TextNode(self.webdriver, r.element) for r in result)
        return SelectorList(result)


    def select_script(self, script, *args):
        """Return elements using JavaScript snippet execution."""
        result = self.webdriver.execute_script(script, *args)
        return SelectorList(self._make_result(result))

    def extract(self):
        """Extract text from selenium element."""
        # when running in pdb, extract can be called by __str__ before __init__
        element = getattr(self,'element')
        return element.text if element else None

    def __str__(self):
        # Don't crash when extract returns None
        data_str = self.extract()
        data = repr(data_str[:40]) if data_str else repr(data_str)
        return "<%s xpath=%r data=%s>" % (type(self).__name__, self._expr, data)
    __repr__ = __str__

    def extract_html(self):
        return self.element.get_attribute('innerHTML')


class _NodeAttribute(object):
    """Works around webdriver XPath inability to select attributes."""
    def __init__(self, element, attribute):
        self.element = element
        self.attribute = attribute

    def extract(self):
        return self.element.get_attribute(self.attribute)


class _TextNode(object):
    """Works around webdriver XPath inability to select text nodes.

    It's a rather contrived element API implementation, it should probably
    be expanded.

    """
    JS_FIND_FIRST_TEXT_NODE = ('return arguments[0].firstChild '
                               '&& arguments[0].firstChild.nodeValue')

    def __init__(self, webdriver, element):
        self.element = element
        self.webdriver = webdriver

    def extract(self):
        args = (self.JS_FIND_FIRST_TEXT_NODE, self.element)
        return self.webdriver.execute_script(*args)
