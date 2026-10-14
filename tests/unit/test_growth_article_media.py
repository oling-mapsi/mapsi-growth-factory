from app.application.services.growth_article_media import attach_illustration
from app.application.services.html_sanitizer import HtmlSanitizer


def test_illustration_is_integrated_once_and_can_move():
    original = '<p>Introduction ERP</p><h2>Cadrage</h2><p>Texte avec <a href="https://oling.fr/erp">ERP</a>.</p>'
    first = attach_illustration(original,asset_id='asset-one',alt='Projet ERP')
    saved = HtmlSanitizer.sanitize(first)
    assert '<figure>' in saved and '<img ' in saved
    assert 'https://oling.fr/erp' in saved
    moved = attach_illustration(saved,asset_id='asset-one',alt='Projet ERP',placement='end')
    assert moved.count('<img ') == 1
    assert moved.endswith('</figure>')


def test_illustration_sanitization_rejects_active_content():
    sanitized = HtmlSanitizer.sanitize('<figure><img src="javascript:alert(1)" onerror="alert(1)" alt="ERP"></figure>')
    assert 'javascript:' not in sanitized and 'onerror' not in sanitized
