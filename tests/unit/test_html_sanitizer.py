from app.application.services.html_sanitizer import HtmlSanitizer


def test_html_sanitizer_removes_dangerous_tags_attrs_and_protocols() -> None:
    html = (
        '<h2 onclick="alert(1)">Titre</h2>'
        '<script>alert(1)</script>'
        '<iframe src="https://evil.test"></iframe>'
        '<a href=" java\nscript:alert(1)" target="_blank">Lien</a>'
        '<a href="https://example.test" target="_blank">OK</a>'
    )

    sanitized = HtmlSanitizer.sanitize(html)

    assert sanitized == '<h2>Titre</h2><a target="_blank" rel="noopener noreferrer">Lien</a><a href="https://example.test" target="_blank" rel="noopener noreferrer">OK</a>'
