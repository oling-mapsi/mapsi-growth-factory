import re
import unicodedata

from bs4 import BeautifulSoup

from app.application.models.editorial_v1 import EditorialArticle, EditorialGenerationContext


_WORD = r"[^\W_][\w'’&-]*"
_NAME = rf"(?:[\"«“](?P<quoted>{_WORD}(?:\s+{_WORD}){{0,3}})[\"»”]|(?P<name>{_WORD}(?:\s+(?-i:[A-ZÀ-ÖØ-Þ][\w'’&-]*)){{0,3}}))"
_REFERENCE = re.compile(
    r"\b(?P<prefix>chez|client(?:e)?|customer|testimony from|testimonial from|"
    r"t[eé]moignage (?:de|du)|r[eé]alisation (?:chez|pour)|caso de [eé]xito (?:de|en))\s+"
    r"(?:(?:nomm[eé]|named|llamado|de|du|des|of|la soci[eé]t[eé]|l['’]entreprise)\s+)?" + _NAME,
    re.IGNORECASE,
)
_FICTIONAL = re.compile(r"\bacme\b", re.IGNORECASE)
_GENERIC = set("un une des de du le la les l d notre nos votre vos leur leurs ses son mon ce cet cette ces aucun chaque tout toute tous chez client clients cliente clientes customer customers team teams stakeholders organizations requirements needs business processes data roles can could may might must should will would has have is are the a an our their its with without de del los las el su sus nuestro nuestros una puede debe necesita necesidades requisitos para como en sur dans doit peut doivent peuvent souhaite souhaitent rencontre rencontrent attend attendent besoins besoin système systeme information projet".split())
_SELF = {"oling", "mapsi"}


def _normalized(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold().strip()


def _documented(name: str, article: EditorialArticle, context: EditorialGenerationContext) -> bool:
    known = {source.source_id for source in context.sources}
    for authorization in context.authorized_client_references:
        ids = set(authorization.source_ids)
        if _normalized(authorization.name) != _normalized(name) or not ids or not ids <= known:
            continue
        if not ids <= set(article.source_ids):
            continue
        if not all(any(source.source_id == source_id and re.search(r"(?<!\w)" + re.escape(name) + r"(?!\w)", source.label + " " + source.summary, re.I) for source in context.sources) for source_id in ids):
            continue
        if any(claim.verified and ids <= set(claim.source_ids) and re.search(r"(?<!\w)" + re.escape(name) + r"(?!\w)", claim.text, re.I) for claim in article.claims):
            return True
    return False


def editorial_text_fields(article: EditorialArticle):
    for field in ("title", "excerpt", "body_text", "meta_title", "meta_description", "call_to_action_label", "primary_keyword"):
        yield field, getattr(article, field)
    soup = BeautifulSoup(article.body_html, "html.parser")
    yield "body_html", soup.get_text(" ", strip=True)
    for index, tag in enumerate(soup.find_all(True)):
        for attribute in ("alt", "title"):
            if tag.get(attribute):
                yield f"body_html.{tag.name}[{index}].{attribute}", str(tag[attribute])
    for field in ("claims", "warnings", "secondary_keywords"):
        for index, item in enumerate(getattr(article, field)):
            yield f"{field}[{index}]" + (".text" if field == "claims" else ""), item.text if field == "claims" else item


def unauthorized_client_references(article: EditorialArticle, context: EditorialGenerationContext):
    for location, text in editorial_text_fields(article):
        matches = [(m.start(), m.end(), m.group(), m.group()) for m in _FICTIONAL.finditer(text)]
        for match in _REFERENCE.finditer(text):
            name = match.group("quoted") or match.group("name")
            key = _normalized(name)
            if key in _GENERIC or key in _SELF:
                continue
            # Ordinary prose is not a named entity. Quoted names and explicit
            # testimonials remain checked even when the brand is lower-case.
            explicit = match.group("quoted") or not re.fullmatch(r"chez|client(?:e)?|customer", match.group("prefix"), re.I)
            if not explicit and not name[0].isupper() and not any(c.isupper() for c in name[1:]):
                continue
            if not _documented(name, article, context):
                matches.append((match.start(), match.end(), match.group(), name))
        seen = set()
        for start, end, exact, name in sorted(matches):
            if (start, end) in seen or _documented(name, article, context):
                continue
            seen.add((start, end))
            yield location, exact, start
