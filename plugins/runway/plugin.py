"""
Plugin Runway - Provider Real (Ticket 011)
Implementación real del pipeline de extracción para Runway AI Film Festival (AIF 2026):
Playwright (primario, páginas con JS/Next.js) -> fallback graceful a httpx.

Pipeline (sin excepciones, igual que cualquier plugin):
Plugin
  ↓
Provider (candidate_urls -> fetch -> extract -> normalize)
  ↓
Normalize
  ↓
Fingerprint
  ↓
History
  ↓
Database
  ↓
Notification

Reglas respetadas:
- No se modifica core/ ni contratos existentes.
- Usa candidate_urls() + fetch_first_success() genéricos de Provider base.
- Playwright se importa lazy dentro del fetch: si no está instalado, falla el browser
  o hay timeout, se captura aislado y se cae a httpx sin romper el pipeline.
"""

from core.provider import Provider, FetchResult, RawOpportunity, NormalizedOpportunity
from typing import List, Dict, Any, Optional
import re
from datetime import datetime, timezone
from bs4 import BeautifulSoup
from core.logger import get_logger

logger = get_logger("provider")


class RunwayProvider(Provider):
    """
    Provider Runway - AI Film Festival (aiff.runwayml.com).

    La página es Next.js: parte de los datos vive en el DOM renderizado y parte en el
    payload RSC embebido (strings JSON escapados con \\" dentro de <script>).
    extract() usa BeautifulSoup para el DOM y regex sobre el payload desescapado
    para deadline y premios (misma estrategia robusta documentada en el diseño).
    """

    # URLs oficiales de Runway AIF (diseño Ticket 011)
    RUNWAY_AIFF_URL = "https://aiff.runwayml.com/"
    RUNWAY_FILM_FESTIVAL_URL = "https://runwayml.com/ai-film-festival"

    FETCH_TIMEOUT_MS = 30000

    @property
    def provider_type(self) -> str:
        return "playwright"  # primario playwright, fallback httpx - ver fetch_single()

    def candidate_urls(self, url: str) -> List[str]:
        """
        URLs candidatas de Runway sin tocar Provider base:
        la pedida + las dos oficiales del AI Film Festival.
        """
        urls = []
        if url:
            urls.append(url)
        for candidate in (self.RUNWAY_AIFF_URL, self.RUNWAY_FILM_FESTIVAL_URL):
            if candidate not in urls:
                urls.append(candidate)
        return urls

    def fetch(self, url: str) -> FetchResult:
        """
        Fetch real usando el método genérico fetch_first_success() de Provider base:
        itera candidate_urls() hasta el primer éxito. Cada intento (fetch_single)
        aplica la estrategia Playwright -> httpx.
        """
        return self.fetch_first_success(url)

    def fetch_single(self, url: str) -> FetchResult:
        """
        Estrategia de fetch de una URL (diseño Ticket 011):
        1. Primario: Playwright (chromium headless) para renderizar JS.
        2. Fallback: ante CUALQUIER excepción o fallo (playwright no instalado,
           browser crash, timeout), log warning y delega a httpx vía
           Provider.fetch_single() base. Nunca propaga excepción al core.
        """
        try:
            result = self._fetch_with_playwright(url)
            if result.success and result.content:
                return result
            logger.warning(f"[Runway] Playwright fetch unsuccessful for {url} ({result.error}), falling back to httpx")
        except Exception as e:
            logger.warning(f"[Runway] Playwright fetch failed {url}: {e} - falling back to httpx")

        # Fallback graceful: httpx con headers Radar (implementación base del contrato)
        fallback = super().fetch_single(url)
        if fallback.success:
            fallback.metadata["fetch_strategy"] = "httpx_fallback"
        return fallback

    def _fetch_with_playwright(self, url: str) -> FetchResult:
        """
        Fetch con Playwright (primario). Import lazy para que el plugin cargue
        aunque playwright no esté instalado (doctor lo trata como opcional).
        Lanza excepción si falla: fetch_single() la captura y cae a httpx.
        """
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                context = browser.new_context(
                    user_agent="Radar/3.0 Opportunity Intelligence (+https://radar.local)",
                    locale="en-US"
                )
                page = context.new_page()
                response = None
                try:
                    response = page.goto(url, wait_until="networkidle", timeout=self.FETCH_TIMEOUT_MS)
                except Exception as e:
                    # networkidle puede no resolverse en SPAs con long-polling: reintentar con domcontentloaded
                    logger.info(f"[Runway] networkidle no resuelto en {url} ({e}), reintentando domcontentloaded")
                    response = page.goto(url, wait_until="domcontentloaded", timeout=self.FETCH_TIMEOUT_MS)

                status_code = response.status if response else 0
                # Dar chance mínima al render cliente si el DOM llega vacío
                try:
                    page.wait_for_timeout(1500)
                except Exception:
                    pass
                content = page.content()

                return FetchResult(
                    success=status_code == 200 and bool(content) and len(content) > 500,
                    content=content if status_code == 200 else None,
                    content_type="html",
                    status_code=status_code,
                    url=url,
                    provider=self.provider_type,
                    error=None if status_code == 200 else f"Status {status_code}",
                    metadata={"fetch_strategy": "playwright"}
                )
            finally:
                try:
                    browser.close()
                except Exception:
                    pass

    # ------------------------------------------------------------------
    # EXTRACT
    # ------------------------------------------------------------------

    @staticmethod
    def _unescape_rsc_payload(content: str) -> str:
        """
        Next.js embebe datos como strings JSON escapados (\\"key\\":\\"value\\", \\u0026).
        Desescapa para poder aplicar regex estables sobre el payload.
        """
        if not content:
            return ""
        return (
            content
            .replace("\\\\", "\x00")      # preservar backslashes literales
            .replace('\\"', '"')
            .replace("\\u0026", "&")
            .replace("\\n", " ")
            .replace("\x00", "\\")
        )

    def extract(self, fetch_result: FetchResult) -> List[RawOpportunity]:
        """
        Extract real desde HTML de Runway AIF (fixture runway_2026.html / página real).
        Extrae:
        - Título: AIF 2026 | AI Festival (og:title / <title> / h1)
        - Descripción: meta description
        - Deadline: "Submission Deadline: April 27th at 4:59 PM ET" (payload RSC)
        - Premios: Grand Prix $50,000 + 1,000,000 credits, Gold $15,000, Silver $10,000...
        - economic_value: máximo cash prize como float (50000.0), currency USD
        """
        if not fetch_result.success or not fetch_result.content:
            logger.warning(f"[Runway] Extract skipped, fetch failed: {fetch_result.error}")
            return []

        try:
            content = fetch_result.content
            soup = BeautifulSoup(content, "lxml")
            unescaped = self._unescape_rsc_payload(content)

            title = self._extract_title(soup)
            description = self._extract_description(soup)
            deadline_text = self._extract_deadline_text(unescaped, soup)
            awards = self._extract_awards(unescaped, soup)

            economic_value = None
            currency = "USD"
            if awards:
                values = [a["amount"] for a in awards if a.get("amount") is not None]
                if values:
                    # Siempre float (evita updates falsos 50000 vs 50000.0 en History)
                    economic_value = float(max(values))

            awards_text = self._build_awards_text(awards)

            edition = None
            edition_match = re.search(r"\b(20\d{2})\b", title or "")
            if edition_match:
                edition = int(edition_match.group(1))
            if edition is None and deadline_text:
                # Fallback: año de contexto (eyebrow "2026" del bloque criteria)
                ctx = re.search(r"\b(20\d{2})\b", unescaped)
                if ctx:
                    edition = int(ctx.group(1))

            raw_data = {
                "title": title,
                "official_link": fetch_result.url,
                "source_url": fetch_result.url,
                "deadline_text": deadline_text,
                "edition": edition,
                "awards": awards,
                "awards_text": awards_text,
                "economic_value": economic_value,
                "currency": currency,
                "description_raw": description,
                "extraction_source": "aiff.runwayml.com",
                "category": "IA / Cine"
            }

            opportunities = [RawOpportunity(
                title=title,
                url=fetch_result.url,
                raw_data=raw_data,
                provider=self.provider_type,
                organization_slug=self.organization_slug or "runway"
            )]

            logger.info(
                f"[Runway] Extracted {len(opportunities)} opportunities: {title} "
                f"deadline={deadline_text} economic_value={economic_value} {currency}"
            )
            return opportunities

        except Exception as e:
            logger.error(f"[Runway] Extract failed: {e}", exc_info=True)
            return []

    def _extract_title(self, soup: BeautifulSoup) -> str:
        """Título: og:title -> <title> -> h1 -> fallback conocido."""
        try:
            og = soup.find("meta", property="og:title")
            if og and og.get("content"):
                candidate = og["content"].strip()
                if 3 < len(candidate) < 200:
                    return candidate

            if soup.title and soup.title.string:
                candidate = re.sub(r"\s+", " ", soup.title.string).strip()
                if 3 < len(candidate) < 200:
                    return candidate

            for tag in soup.find_all(["h1", "h2"]):
                txt = re.sub(r"\s+", " ", tag.get_text(strip=True))
                if "AIF" in txt or "Film Festival" in txt or "Runway" in txt:
                    if 3 < len(txt) < 200:
                        return txt
        except Exception as e:
            logger.warning(f"[Runway] Title extraction failed: {e}")
        return "Runway AI Film Festival"

    def _extract_description(self, soup: BeautifulSoup) -> str:
        """Descripción: meta description -> og:description -> párrafos largos."""
        try:
            meta = soup.find("meta", attrs={"name": "description"})
            if meta and meta.get("content"):
                candidate = meta["content"].strip()
                if len(candidate) > 30:
                    return candidate

            og = soup.find("meta", property="og:description")
            if og and og.get("content"):
                candidate = og["content"].strip()
                if len(candidate) > 30:
                    return candidate

            paragraphs = []
            for p in soup.find_all("p"):
                txt = re.sub(r"\s+", " ", p.get_text(strip=True))
                if len(txt) > 80:
                    paragraphs.append(txt)
                    if len(" ".join(paragraphs)) > 400:
                        break
            if paragraphs:
                return " ".join(paragraphs)[:1000]
        except Exception as e:
            logger.warning(f"[Runway] Description extraction failed: {e}")
        return "Runway AI Film Festival (AIF) - celebration of creatives experimenting at the forefront of art and technology with generative AI."

    def _extract_deadline_text(self, unescaped: str, soup: BeautifulSoup) -> Optional[str]:
        """
        Deadline: 'Submission Deadline: April 27th at 4:59 PM ET'
        Vive en el payload RSC (bloque criteria). Fallback: regex sobre texto visible.
        """
        try:
            # 1) Payload RSC: "deadline":"Submission Deadline: April 27th at 4:59 PM ET"
            match = re.search(
                r'"deadline"\s*:\s*"(?:Submission )?[Dd]eadline[:\s]*([^"]+?)"',
                unescaped
            )
            if not match:
                # 2) Genérico sobre payload: Submission Deadline: <fecha>
                match = re.search(
                    r'[Ss]ubmission\s+[Dd]eadline\s*:\s*([A-Za-z]+\s+\d{1,2}(?:st|nd|rd|th)?[^"<]{0,40})',
                    unescaped
                )
            if not match:
                # 3) Texto visible renderizado
                match = re.search(
                    r'[Ss]ubmission\s+[Dd]eadline\s*:\s*([A-Za-z]+\s+\d{1,2}(?:st|nd|rd|th)?[^"<]{0,40})',
                    soup.get_text(" ")
                )

            if match:
                deadline = re.sub(r"\s+", " ", match.group(1)).strip(" .;,")
                if deadline:
                    return deadline
        except Exception as e:
            logger.warning(f"[Runway] Deadline extraction failed: {e}")

        logger.warning("[Runway] Deadline not found in HTML")
        return None

    def _extract_awards(self, unescaped: str, soup: BeautifulSoup) -> List[Dict[str, Any]]:
        """
        Premios. Primario: payload RSC
            {"place":"Grand Prix","prize":"$$50,000","description":"Cash prize & 1,000,000 Runway credits"}
        Fallback: DOM renderizado
            <div class="rw-h6">Grand Prix / $50,000</div><div ...>Cash prize & ... credits</div>
        Dedupe por (place, amount). amount siempre float.
        """
        awards: List[Dict[str, Any]] = []
        seen = set()

        def add_award(place: str, amount_str: str, description: str = "", category: str = ""):
            place = re.sub(r"\s+", " ", (place or "")).strip(" /-")
            if not place:
                return
            try:
                amount = float(re.sub(r"[^\d.]", "", amount_str))
            except (ValueError, TypeError):
                return
            key = (place.lower(), amount)
            if key in seen:
                return
            seen.add(key)
            awards.append({
                "place": place,
                "amount": amount,
                "description": re.sub(r"\s+", " ", (description or "")).strip(),
                "category": category
            })

        try:
            # Primario: payload RSC desescapado
            for match in re.finditer(
                r'"place"\s*:\s*"([^"]+?)"\s*,\s*"prize"\s*:\s*"\$+\s*([\d,.]+)"\s*,\s*"description"\s*:\s*"([^"]*?)"',
                unescaped
            ):
                add_award(match.group(1), match.group(2), match.group(3))
        except Exception as e:
            logger.warning(f"[Runway] Awards JSON extraction failed: {e}")

        if not awards:
            try:
                # Fallback: DOM (AIF renderizado: "Grand Prix / $50,000" + descripción)
                for tag in soup.find_all(class_="rw-h6"):
                    txt = re.sub(r"\s+", " ", tag.get_text(" ", strip=True))
                    m = re.match(r"^(.*?)\s*/\s*\$\s*([\d,.]+)\s*$", txt)
                    if not m:
                        continue
                    desc_tag = tag.find_next(
                        lambda t: t.name == "div" and t.get("class")
                        and any("rw-bodycopy" in cls for cls in t.get("class", []))
                    )
                    desc = desc_tag.get_text(" ", strip=True) if desc_tag else ""
                    add_award(m.group(1), m.group(2), desc)
            except Exception as e:
                logger.warning(f"[Runway] Awards DOM extraction failed: {e}")

        # Orden determinista: mayor premio primero
        awards.sort(key=lambda a: a["amount"], reverse=True)
        return awards

    @staticmethod
    def _build_awards_text(awards: List[Dict[str, Any]]) -> str:
        """'Grand Prix $50,000 (Cash prize & 1,000,000 Runway credits); Gold $15,000 (...)'"""
        parts = []
        for a in awards:
            amount_fmt = f"${a['amount']:,.0f}"
            if a.get("description"):
                parts.append(f"{a['place']} {amount_fmt} ({a['description']})")
            else:
                parts.append(f"{a['place']} {amount_fmt}")
        return "; ".join(parts)

    # ------------------------------------------------------------------
    # NORMALIZE
    # ------------------------------------------------------------------

    @staticmethod
    def _et_tzinfo(reference: datetime):
        """
        Zona horaria 'ET' = America/New_York (respeta EST/EDT).
        Cadena de fallbacks: zoneinfo -> dateutil.gettz -> offset fijo por mes
        (marzo-noviembre: EDT UTC-4; resto: EST UTC-5). Nunca lanza.
        """
        try:
            from zoneinfo import ZoneInfo
            return ZoneInfo("America/New_York")
        except Exception:
            pass
        try:
            from dateutil import tz as dateutil_tz
            tzinfo = dateutil_tz.gettz("America/New_York")
            if tzinfo is not None:
                return tzinfo
        except Exception:
            pass
        try:
            from dateutil import tz as dateutil_tz
            offset = -14400 if 3 <= reference.month <= 11 else -18000
            return dateutil_tz.tzoffset("ET", offset)
        except Exception:
            return timezone.utc

    def _parse_deadline_to_iso(self, deadline_text: Optional[str], edition: Optional[int]) -> Optional[str]:
        """
        'April 27th at 4:59 PM ET' + edición (2026) -> ISO 8601 en UTC.
        Ej: 2026-04-27T20:59:00+00:00 (abril -> EDT, UTC-4).
        Si no puede parsear de forma segura retorna None (el texto queda en extra_json).
        """
        if not deadline_text:
            return None
        try:
            from dateutil import parser as dateutil_parser

            m = re.search(
                r'([A-Za-z]+)\s+(\d{1,2})(?:st|nd|rd|th)?\s*,?\s*(?:(\d{4}))?\s*(?:at\s+(\d{1,2}):(\d{2})\s*([AP]M)\s*ET)?',
                deadline_text,
                re.IGNORECASE
            )
            if not m:
                # Intento genérico con dateutil sobre el texto limpio
                cleaned = re.sub(r"(\d)(st|nd|rd|th)", r"\1", deadline_text)
                cleaned = re.sub(r"\bET\b", "", cleaned).strip(" ,")
                dt = dateutil_parser.parse(cleaned, default=datetime(edition or datetime.now().year, 1, 1))
                naive = dt.replace(tzinfo=None)
            else:
                month_name, day, year_str, hour_str, minute_str, ampm = m.groups()
                year = int(year_str) if year_str else (edition or datetime.now().year)
                hour = int(hour_str) if hour_str else 23
                minute = int(minute_str) if minute_str else 59
                if ampm:
                    ampm = ampm.upper()
                    if ampm == "PM" and hour != 12:
                        hour += 12
                    elif ampm == "AM" and hour == 12:
                        hour = 0
                month = dateutil_parser.parse(f"{month_name} 1 {year}").month
                naive = datetime(year, month, int(day), hour, minute)

            localized = naive.replace(tzinfo=self._et_tzinfo(naive))
            return localized.astimezone(timezone.utc).isoformat()
        except Exception as e:
            logger.warning(f"[Runway] Deadline normalize failed for '{deadline_text}': {e}")
            return None

    def normalize(self, raw: RawOpportunity) -> NormalizedOpportunity:
        """
        Normaliza RawOpportunity a formato canónico Radar.
        Flujo: Provider (fetch+extract) -> Normalize -> Fingerprint -> Database -> Logs
        Tipos garantizados: economic_value float, deadline ISO 8601 UTC o None.
        """
        try:
            data = raw.raw_data or {}

            title = data.get("title") or raw.title or "Runway AI Film Festival"
            title = re.sub(r"\s+", " ", title).strip()

            deadline_text = data.get("deadline_text")
            edition = data.get("edition")
            deadline_iso = self._parse_deadline_to_iso(deadline_text, edition)

            awards = data.get("awards", [])
            awards_text = data.get("awards_text", "")

            economic_value = data.get("economic_value")
            if economic_value is not None:
                try:
                    economic_value = float(economic_value)  # siempre float
                except (ValueError, TypeError):
                    economic_value = None
            currency = data.get("currency", "USD")

            description_raw = data.get("description_raw", "")
            description_clean = description_raw[:500] if description_raw else ""

            official_link = data.get("official_link") or raw.url or self.RUNWAY_AIFF_URL

            return NormalizedOpportunity(
                title=title,
                organizer_name="Runway",
                organization_slug=self.organization_slug or "runway",
                official_link=official_link,
                description_raw=description_raw,
                description_clean=description_clean,
                deadline=deadline_iso,
                awards_text=awards_text,
                economic_value=economic_value,
                currency=currency,
                category="IA / Cine",
                opportunity_type="festival",
                language="Inglés",
                source_url=raw.url,
                provider=self.provider_type,
                extra_json={
                    "awards": awards,
                    "deadline_text": deadline_text,
                    "edition": edition,
                    "extraction_source": data.get("extraction_source", "aiff.runwayml.com"),
                    "screening_events": "Los Angeles & Tokyo"
                }
            )

        except Exception as e:
            logger.error(f"[Runway] Normalize failed for {raw.title}: {e}", exc_info=True)
            # Fallback mínimo para no romper pipeline
            return NormalizedOpportunity(
                title=raw.title or "Runway AI Film Festival",
                organizer_name="Runway",
                organization_slug=self.organization_slug or "runway",
                official_link=raw.url or self.RUNWAY_AIFF_URL,
                description_raw="Runway AI Film Festival (AIF) - AI film festival and competition.",
                source_url=raw.url,
                provider=self.provider_type
            )
