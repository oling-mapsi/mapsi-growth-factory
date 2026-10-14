from __future__ import annotations

from html.parser import HTMLParser


class HtmlSanitizer(HTMLParser):
    ALLOWED_TAGS = {"p", "br", "strong", "em", "b", "i", "u", "ul", "ol", "li", "a", "h1", "h2", "h3", "blockquote", "figure", "figcaption", "img"}
    ALLOWED_ATTRS = {"a": {"href", "title", "target", "rel"}, "img": {"src", "alt", "loading"}}
    BLOCKED_TAGS = {"script", "style", "iframe", "object", "embed"}
    BLOCKED_PROTOCOLS = ("javascript:", "data:", "vbscript:")

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.blocked_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in self.BLOCKED_TAGS:
            self.blocked_depth += 1
            return
        if self.blocked_depth or tag not in self.ALLOWED_TAGS:
            return
        safe_attrs: list[str] = []
        for name, value in attrs:
            name = name.lower()
            value = value or ""
            if name.startswith("on") or name not in self.ALLOWED_ATTRS.get(tag, set()):
                continue
            if name in {"href", "src"} and self._has_blocked_protocol(value):
                continue
            if tag == "a" and name == "target" and value != "_blank":
                continue
            safe_attrs.append(f'{name}="{self._escape(value)}"')
        if tag == "a" and any(item.startswith('target="_blank"') for item in safe_attrs) and not any(item.startswith("rel=") for item in safe_attrs):
            safe_attrs.append('rel="noopener noreferrer"')
        suffix = (" " + " ".join(safe_attrs)) if safe_attrs else ""
        self.parts.append(f"<{tag}{suffix}>")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in self.BLOCKED_TAGS and self.blocked_depth:
            self.blocked_depth -= 1
            return
        if not self.blocked_depth and tag in self.ALLOWED_TAGS:
            self.parts.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        if not self.blocked_depth:
            self.parts.append(self._escape(data))

    @classmethod
    def sanitize(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parser = cls()
        parser.feed(value)
        parser.close()
        return "".join(parser.parts)

    @classmethod
    def _has_blocked_protocol(cls, value: str) -> bool:
        compact = "".join(value.split()).lower()
        return compact.startswith(cls.BLOCKED_PROTOCOLS)

    @staticmethod
    def _escape(value: str) -> str:
        return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
