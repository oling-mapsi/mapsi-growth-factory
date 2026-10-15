"""Per-version human acceptance; never rewrites the machine quality report."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime

POLICY_VERSION = 1
_SENSITIVE = re.compile(r"\d|[%€$]|\b(?:guarantee\w*|garanti\w*|garantiz\w*|medical\w*|médic\w*|legal\w*|juridi\w*|jurídic\w*|certifi\w*|revenue|turnover|chiffre d.affaires|confidential\w*)\b", re.I)
_MANUAL = {'manual_content_changed', 'editorial_content_mismatch'}
_CRITICAL = {'unauthorized_client_reference', 'unsafe_html', 'secret_or_email_detected', 'sensitive_fact', 'dangerous_content'}


def _has_sensitive_claim(text: str) -> bool:
    for match in _SENSITIVE.finditer(text):
        term = match.group().casefold()
        if term.startswith(('guarantee', 'garanti', 'garantiz')):
            prefix, suffix = text[:match.start()], text[match.end():]
            negated = re.search(r'\b(?:no|not|never|without|sans|sin)\s+$', prefix, re.I)
            french_negation = re.search(r'\bne\s+$', prefix, re.I) and re.match(r'\s+(?:pas|jamais|aucun|aucune)\b', suffix, re.I)
            if negated or french_negation:
                continue
        return True
    return False


def editorial_readiness(asset) -> dict:
    quality = dict((asset.results or {}).get('editorial_quality') or {})
    claims = ((asset.results or {}).get('editorial_article') or {}).get('claims') or []
    issues = [issue for issue in quality.get('issues', []) if isinstance(issue, dict)]
    missing = [claim for claim in claims if isinstance(claim, dict) and not claim.get('source_ids')]
    missing_issues = [issue for issue in issues if issue.get('code') == 'claim_without_source']
    can_accept_missing = bool(missing) and len(missing) == len(missing_issues) and all(
        claim.get('claim_type') in {'generic_guidance', 'editorial_positioning'}
        and bool(str(claim.get('text', '')).strip()) and not _has_sensitive_claim(claim['text'])
        and not claim.get('critical') and not claim.get('sensitive') for claim in missing
    )
    warnings, blockers = [], []
    for issue in issues:
        if issue.get('code') == 'claim_without_source' and can_accept_missing:
            warnings.append(dict(issue))
        elif issue.get('severity', '').lower() in {'error', 'blocking', 'critical'} or issue.get('code') in _CRITICAL:
            blockers.append(dict(issue))
    if quality and not quality.get('passed', False) and not warnings and not blockers:
        blockers.append({'code': 'unclassified_quality_failure', 'message': 'Quality failure requires review.'})
    signature = hashlib.sha256(json.dumps({'quality': quality, 'claims': claims}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    receipt = (asset.results or {}).get('human_editorial_acceptance') or {}
    accepted = bool(warnings) and not blockers and bool(receipt.get('actor')) and bool(receipt.get('confirmed_at')) \
        and receipt.get('policy_version') == POLICY_VERSION and receipt.get('version') == asset.content_version \
        and receipt.get('content_hash') == asset.content_hash and receipt.get('quality_signature') == signature
    revalidation_pending = bool(blockers) and all(issue.get('code') in _MANUAL for issue in blockers)
    return {'quality_blocking': bool(blockers) or (bool(warnings) and not accepted),
            'critical_issues': blockers, 'editorial_warnings': warnings, 'warnings_accepted': accepted,
            'human_review_pending': (bool(warnings) and not blockers and not accepted) or revalidation_pending,
            'quality_signature': signature}


def accept_editorial_warnings(asset, actor: str) -> None:
    from app.domain.errors import ApprovalPrerequisiteError
    state = editorial_readiness(asset)
    if state['critical_issues']:
        raise ApprovalPrerequisiteError('Critical editorial issues must be corrected before approval.')
    if state['editorial_warnings']:
        if not actor.strip():
            raise ApprovalPrerequisiteError('An identified human reviewer is required.')
        asset.results = {**asset.results, 'human_editorial_acceptance': {
            'actor': actor, 'confirmed_at': datetime.now(UTC).isoformat(), 'version': asset.content_version,
            'content_hash': asset.content_hash, 'quality_signature': state['quality_signature'],
            'policy_version': POLICY_VERSION, 'accepted_warnings': state['editorial_warnings'],
            'scope': 'asset', 'asset_id': asset.id, 'channel': asset.channel, 'locale': asset.locale,
        }}
