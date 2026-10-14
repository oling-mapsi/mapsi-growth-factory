from __future__ import annotations

import base64
import time
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import httpx

from app.core.config import get_settings


@dataclass(frozen=True)
class GrowthImageResult:
    model: str
    prompt: str
    alt_text: str
    storage_path: str
    data_url: str
    output_format: str
    duration_ms: int
    tokens: dict[str, int]


class GrowthImageGenerationService:
    def __init__(self, *, project_root: Path) -> None:
        self.project_root = project_root
        self.settings = get_settings()

    def generate(self, *, channel: str, title: str, content_text: str, visual_brief: str = "", locale: str = 'fr-FR') -> GrowthImageResult:
        prompt = self._prompt(channel=channel, title=title, content_text=content_text, visual_brief=visual_brief)
        started = time.perf_counter()
        model = self.settings.growth_image_model
        try:
            payload = self._call_openai(prompt, model)
        except httpx.HTTPStatusError as exc:
            try:
                code = exc.response.json().get("error", {}).get("code")
            except (ValueError, AttributeError):
                code = None
            if exc.response.status_code not in {400, 404} or code not in {"model_not_found", "unsupported_model"}:
                raise
            payload = self._call_openai(prompt, self.settings.growth_image_fallback_model)
            model = self.settings.growth_image_fallback_model
        if not payload.get("data"):
            raise ValueError("Image provider returned no image; no automatic paid retry was attempted.")
        image = payload["data"][0]
        raw = base64.b64decode(image["b64_json"])
        output_format = str(payload.get("output_format") or "png")
        storage_dir = self.project_root / self.settings.growth_media_storage_dir
        storage_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{uuid4()}.{output_format}"
        path = storage_dir / filename
        path.write_bytes(raw)
        usage = payload.get("usage") or {}
        return GrowthImageResult(
            model=model,
            prompt=prompt,
            alt_text=self._alt_text(channel=channel, title=title, locale=locale),
            storage_path=str(path.relative_to(self.project_root)),
            data_url=f"data:image/{output_format};base64,{image['b64_json']}",
            output_format=output_format,
            duration_ms=max(1, int((time.perf_counter() - started) * 1000)),
            tokens={
                "input": int(usage.get("input_tokens") or 0),
                "output": int(usage.get("output_tokens") or 0),
                "total": int(usage.get("total_tokens") or 0),
            },
        )

    def _call_openai(self, prompt: str, model: str) -> dict:
        with httpx.Client(timeout=self.settings.editorial_agent_timeout_seconds) as client:
            response = client.post(
                "https://api.openai.com/v1/images/generations",
                headers={"Authorization": f"Bearer {self.settings.openai_api_key}"},
                json={
                    "model": model,
                    "prompt": prompt,
                    "n": 1,
                    "size": self.settings.growth_image_size,
                    "quality": self.settings.growth_image_quality,
                    "output_format": "png",
                },
            )
        response.raise_for_status()
        return response.json()

    def _prompt(self, *, channel: str, title: str, content_text: str, visual_brief: str) -> str:
        site = "MAPSI" if channel == "mapsi_site" else "OLING"
        guardrail = (
            "Ne pas inventer de capture d'ecran, client, mission, resultat chiffre ou interface presentee comme reelle. "
            "Produire un visuel editorial professionnel, abstrait mais concret, compatible web."
        )
        return "\n".join(
            [
                f"Destination: {site}",
                f"Titre article: {title}",
                f"Brief visuel utilisateur: {visual_brief or 'illustration professionnelle coherente avec le contenu'}",
                f"Extrait article: {content_text[:1200]}",
                guardrail,
            ]
        )

    def _alt_text(self, *, channel: str, title: str, locale: str = 'fr-FR') -> str:
        site = "MAPSI" if channel == "mapsi_site" else "OLING"
        prefix = {'en-US':f'Editorial illustration {site}: ', 'es-ES':f'Ilustracion editorial {site}: '}.get(locale,f"Illustration {site} pour l'article : ")
        return prefix + title[:120]
