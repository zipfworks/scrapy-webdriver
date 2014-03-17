import re

from scrapy.selector import Selector, SelectorList

_UNSUPPORTED_XPATH_ENDING = re.compile(r'.*/((@)?([^/()]+)(\(\))?)$')
_UNSUPPORTED_CSS_ENDING = re.compile(r'.*(::text|::attr\(([\w-]+)\))$')


GET_TEXT_CONTENT = """
var getTextContent = function(node,recurse) {
    var children = node.childNodes;
    var content = [];
    for (var i = 0; i < children.length; i++) {
        var child = children[i];
        if (child.nodeType == Node.TEXT_NODE) {
            content.push(child.textContent);
        }
        if (recurse && child.nodeType == Node.ELEMENT_NODE) {
            content.push.apply(content,getTextContent(child,true));
        }
    }
    return content;
}
return getTextContent.apply(null, arguments)
"""

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

    def css(self, css):
        """Return elements using the webdriver `find_elements_by_css` method.
        This adds support for useful css psuedo-selectors:
          - a.clicky::attr(href)
          - h2.heading::text
          - h2.heading ::text
        """
        elem = self.element if self.element else self.webdriver
        psuedo, recurse, attr = None, False, None
        ending = _UNSUPPORTED_CSS_ENDING.match(css)
        if ending:
            psuedo, attr = ending.groups()
            css = css[:-len(psuedo)]
            # "h2 ::text" visits child nodes recursively"
            if css.endswith(' '):
                recurse = True
                css = css[:-1]

        elems = elem.find_elements_by_css_selector(css)
        is_text = (psuedo == '::text')
        return self._make_selector_list(elems, is_text, recurse, attr)

    def xpath(self, xpath):
        """Return elements using the webdriver `find_elements_by_xpath` method.

        Some XPath features are not supported by the webdriver implementation.
        Namely, selecting text content or attributes:
          - /some/element/text()
          - /some/element//text()
          - /some/element/@attribute

        This function offers workarounds for both, so it should be safe to use
        them as you would with HtmlXPathSelector for simple content extraction.

        """
        xpathev = self.element if self.element else self.webdriver
        ending = _UNSUPPORTED_XPATH_ENDING.match(xpath)
        atsign = parens = None
        is_text, recurse, attr = False, False, None
        if ending:
            _, atsign, name, parens = ending.groups()
            if atsign:
                xpath = xpath[:-len(name) - 2]
                attr = name
            elif parens and name == 'text':
                xpath = xpath[:-len(name) - 3]
                is_text = True
                # do the right thing for /some/div//text()
                if xpath.endswith('/'):
                    xpath = xpath[:-1]
                    recurse = True

        elems = xpathev.find_elements_by_xpath(xpath)
        return self._make_selector_list(elems, is_text, recurse, attr)

    def select_script(self, script, *args):
        """Return elements using JavaScript snippet execution."""
        result = self.webdriver.execute_script(script, *args)
        return SelectorList(self._make_result(result))

    def _make_result(self, result):
        if type(result) is not list:
            result = [result]
        return [self.__class__(webdriver=self.webdriver, element=e)
                for e in result]

    def _make_selector_list(self, elems, is_text, text_recurse, attr):
        if type(elems) is not list:
            elems = [elems]

        if is_text:
            return SelectorList(
                _TextNode(self.webdriver, s)
                for elem in elems
                for s in self._text_content(elem, text_recurse)
            )

        selectors = self._make_result(elems)
        if attr:
            selectors = (_NodeAttribute(s.element, attr) for s in selectors)
        return SelectorList(selectors)

    def _text_content(self, element, recurse):
        return self.webdriver.execute_script(GET_TEXT_CONTENT,
                                             element, recurse)

    def extract(self):
        """Extract text from selenium element."""
        # when running in pdb, extract can be called by __str__ before __init__
        element = getattr(self, 'element')
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
    """
    def __init__(self, webdriver, text):
        self.text = text
        self.webdriver = webdriver

    def extract(self):
        return self.text
