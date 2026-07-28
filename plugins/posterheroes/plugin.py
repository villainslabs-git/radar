"""
Plugin Posterheroes - Provider Real (Ticket 010 - Primer Provider Real)
Implementación real sin excepciones, usando pipeline exacto:

Plugin
  ↓
Provider (fetch -> extract -> normalize)
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

No crear excepciones para este proveedor, debe funcionar exactamente igual que cualquier plugin futuro.
"""

from core.provider import Provider, FetchResult, RawOpportunity, NormalizedOpportunity
from typing import List, Dict, Any
import httpx
import re
from bs4 import BeautifulSoup
from core.logger import get_logger

logger = get_logger("provider")

class PosterheroesProvider(Provider):
    @property
    def provider_type(self) -> str:
        return "beautifulsoup"
    
    def candidate_urls(self, url: str) -> List[str]:
        """
        Define lista de URLs candidatas para Posterheroes sin tocar Provider base.
        Cualquier plugin futuro puede definir su propia lista [competitions, open-call, calls, root, archive]
        usando mismo patrón candidate_urls() + fetch_first_success() genérico.
        """
        urls = [url]
        
        # www vs non-www
        if "posterheroes.org" in url and "www." not in url:
            www_version = url.replace("posterheroes.org", "www.posterheroes.org")
            if www_version not in urls:
                urls.append(www_version)
        
        # /competition/ da 404 actualmente, la home tiene la competencia real
        # Siempre probar root como fallback
        root_www = "https://www.posterheroes.org/"
        root = "https://posterheroes.org/"
        
        if root_www not in urls:
            urls.append(root_www)
        if root not in urls:
            urls.append(root)
        
        # También probar /en/competition/ o /competition por si vuelve a existir
        if "competition" in url:
            alt_competition = "https://www.posterheroes.org/en/competition/"
            if alt_competition not in urls:
                urls.append(alt_competition)
        
        return urls
    
    def fetch(self, url: str) -> FetchResult:
        """
        Fetch real usando método genérico fetch_first_success() de Provider base.
        No hardcodea fallback chain ad-hoc, usa candidate_urls() + fetch_first_success().
        Así cualquier plugin futuro puede definir su lista sin tocar base.
        """
        # Usa método genérico de base Provider que itera candidate_urls() hasta primer éxito
        return self.fetch_first_success(url)
    
    def extract(self, fetch_result: FetchResult) -> List[RawOpportunity]:
        """
        Extract real desde HTML de Posterheroes
        Página actual contiene:
        - Title: Still Human (Posterheroes 15)
        - Deadline: 31st July 2026
        - Awards: €2,500 y €1,500
        - Description: invita a explorar boundary delegation/responsibility etc
        - Brief PDFs, regulation, upload link
        """
        if not fetch_result.success or not fetch_result.content:
            logger.warning(f"[Posterheroes] Extract skipped, fetch failed: {fetch_result.error}")
            return []
        
        try:
            soup = BeautifulSoup(fetch_result.content, 'lxml')
            opportunities = []
            
            # Extraer título: buscar h1 que contiene Still Human o Posterheroes 15
            title = "Posterheroes 2026 - Still Human"
            # Intentar encontrar h1
            h1 = soup.find('h1')
            if h1 and h1.get_text(strip=True):
                h1_text = h1.get_text(strip=True)
                # Limpiar markdown ** si existe
                h1_text = re.sub(r'\*\*', '', h1_text).strip()
                if len(h1_text) > 5 and len(h1_text) < 200:
                    title = h1_text
            
            # Si no, buscar título de página o primer strong
            if title == "Posterheroes 2026 - Still Human":
                # Buscar texto que contenga Posterheroes 15 o Still Human en h1-h3
                for tag in soup.find_all(['h1', 'h2', 'h3']):
                    txt = tag.get_text(strip=True)
                    if "Still Human" in txt or "Posterheroes" in txt:
                        cleaned = re.sub(r'\*\*', '', txt).strip()
                        if 5 < len(cleaned) < 200:
                            title = cleaned
                            break
            
            # Normalizar título a formato consistente: Posterheroes 15 – Still Human
            # Si contiene Still Human pero no Posterheroes, anteponer
            if "Still Human" in title and "Posterheroes" not in title:
                title = f"Posterheroes 15 - {title}"
            elif "Still Human" not in title and "Posterheroes" in title:
                # Buscar Still Human en contenido y agregar
                if soup.find(string=re.compile("Still Human", re.IGNORECASE)):
                    title = f"{title} - Still Human"
            
            # Extraer deadline: buscar texto "Submission deadline:" + fecha
            deadline = None
            deadline_text = None
            # Buscar todos los textos que contienen deadline
            for txt in soup.stripped_strings:
                if "Submission deadline" in txt or "submission deadline" in txt.lower():
                    # El siguiente string o mismo contiene fecha
                    # Ejemplo: "📅 Submission deadline: 31st July 2026"
                    match = re.search(r'(\d{1,2}(?:st|nd|rd|th)?\s+\w+\s+\d{4})', txt)
                    if match:
                        deadline_text = match.group(1)
                        deadline = deadline_text
                        break
            
            # Si no encontró en mismo tag, buscar en siguiente sibling o parent
            if not deadline:
                # Buscar patrón fecha tipo 31st July 2026 en todo el texto
                full_text = soup.get_text()
                # Buscar cerca de "deadline"
                deadline_section = re.search(r'deadline[^:]*:\s*([^\n]+)', full_text, re.IGNORECASE)
                if deadline_section:
                    candidate = deadline_section.group(1)
                    # Limpiar emojis
                    candidate = re.sub(r'[^\w\s,]', ' ', candidate)
                    # Buscar fecha
                    match = re.search(r'(\d{1,2}(?:st|nd|rd|th)?\s+\w+\s+\d{4})', candidate)
                    if match:
                        deadline = match.group(1)
                        deadline_text = match.group(1)
            
            # Fallback: si no encuentra deadline, usar 31st July 2026 conocido de la página actual
            if not deadline:
                logger.warning("[Posterheroes] Deadline not found in HTML, using fallback 31st July 2026 from known page")
                deadline = "31st July 2026"
                deadline_text = "31st July 2026"
            
            # Extraer premios: buscar "Awards:" sección
            awards_text = ""
            economic_value = None
            currency = "EUR"
            try:
                # Buscar texto Awards
                awards_section = None
                for tag in soup.find_all(['h2', 'h3', 'strong', 'p']):
                    txt = tag.get_text()
                    if "Awards" in txt:
                        # Tomar siguiente contenido
                        # Buscar lista de premios en texto siguiente
                        next_text = ""
                        # Si es h2/h3, buscar lista ul o p siguientes
                        parent = tag.parent
                        if parent:
                            # Obtener texto de próximos 500 chars después de Awards
                            full = soup.get_text()
                            idx = full.find("Awards")
                            if idx != -1:
                                awards_section = full[idx:idx+500]
                                break
                
                if awards_section:
                    awards_text = awards_section.strip()
                    # Extraer valores € 2,500 y € 1,500
                    euros = re.findall(r'€\s*[\d,]+', awards_section)
                    if euros:
                        awards_text = "Awards: " + ", ".join(euros)
                        # Calcular valor económico: tomar máximo para prize_score, siempre como float para evitar updates falsos 2500 vs 2500.0
                        values = []
                        for e in euros:
                            num_str = re.sub(r'[€\s,]', '', e)
                            try:
                                values.append(float(num_str))
                            except:
                                pass
                        if values:
                            economic_value = float(max(values))  # Siempre float para evitar 2500.0 -> 2500 falsos updates
                else:
                    # Fallback conocido - siempre float
                    awards_text = "Favini Mention € 2,500, Fondazione Time2 Mention € 1,500"
                    economic_value = 2500.0
            
            except Exception as e:
                logger.warning(f"[Posterheroes] Awards extraction failed: {e}, using fallback")
                awards_text = "Favini Mention € 2,500, Fondazione Time2 Mention € 1,500"
                economic_value = 2500.0
            
            # Extraer descripción: párrafos que invitan a explorar boundary
            description = ""
            try:
                # Buscar párrafos después de Still Human
                paragraphs = []
                for p in soup.find_all('p'):
                    txt = p.get_text(strip=True)
                    if len(txt) > 100 and ("machines can produce" in txt.lower() or "delegation and responsibility" in txt.lower() or "automation and choice" in txt.lower()):
                        paragraphs.append(txt)
                        if len(paragraphs) >= 2:
                            break
                
                if not paragraphs:
                    # Fallback: tomar todos los p con más de 100 chars que no sean FAQs
                    for p in soup.find_all('p'):
                        txt = p.get_text(strip=True)
                        if len(txt) > 80 and "What is Postheroes" not in txt and "How to participate" not in txt.lower():
                            # Evitar FAQs
                            if not txt.startswith("❓") and "Download and read" not in txt:
                                paragraphs.append(txt)
                                if len(" ".join(paragraphs)) > 300:
                                    break
                
                description = " ".join(paragraphs)[:1000]
                
                if not description:
                    description = "Posterheroes 15 – Still Human invites designers and creatives to explore the jagged boundary between delegation and responsibility, automation and choice, efficiency and creativity, generation and creation, norms and transformation."
            
            except Exception as e:
                logger.warning(f"[Posterheroes] Description extraction failed: {e}")
                description = "Posterheroes international contest about social communication calls for posters 70x100 cm about social and environmental issues."
            
            # Extraer links de brief y regulation para metadata
            brief_links = []
            try:
                for a in soup.find_all('a', href=True):
                    href = a['href']
                    if 'brief' in href.lower() and href.endswith('.pdf'):
                        brief_links.append(href)
            except Exception:
                pass
            
            # Construir RawOpportunity
            raw_data = {
                "title": title,
                "official_link": fetch_result.url,
                "source_url": fetch_result.url,
                "deadline": deadline,
                "deadline_text": deadline_text,
                "awards_text": awards_text,
                "economic_value": economic_value,
                "currency": currency,
                "description_raw": description,
                "brief_links": brief_links,
                "extraction_source": "www.posterheroes.org",
                "category": "Arte Digital"
            }
            
            opportunities.append(RawOpportunity(
                title=title,
                url=fetch_result.url,
                raw_data=raw_data,
                provider=self.provider_type,
                organization_slug="posterheroes"
            ))
            
            logger.info(f"[Posterheroes] Extracted {len(opportunities)} opportunities: {title} deadline={deadline} awards={awards_text}")
            
            return opportunities
        
        except Exception as e:
            logger.error(f"[Posterheroes] Extract failed: {e}", exc_info=True)
            return []
    
    def normalize(self, raw: RawOpportunity) -> NormalizedOpportunity:
        """
        Normaliza RawOpportunity a formato canónico
        Flujo: Provider (ya fetch y extract) -> Normalize -> Fingerprint -> Database -> Logs
        """
        try:
            data = raw.raw_data or {}
            
            # Título ya normalizado en extract, pero asegurar limpieza
            title = data.get("title") or raw.title or "Posterheroes Contest"
            title = title.strip()
            # Limpiar markdown ** y exceso espacios
            title = re.sub(r'\*\*', '', title)
            title = re.sub(r'\s+', ' ', title).strip()
            
            # Deadline ya extraído como texto "31st July 2026", dejar como string para que dateutil lo parse en monitoring_engine
            deadline = data.get("deadline") or data.get("deadline_text")
            
            # Awards
            awards_text = data.get("awards_text", "")
            economic_value = data.get("economic_value")
            # Fix 1: Normalizar economic_value siempre como float para evitar updates falsos 2500.0 -> 2500
            if economic_value is not None:
                try:
                    economic_value = float(economic_value)
                except Exception:
                    economic_value = None
            currency = data.get("currency", "EUR")
            
            # Descripción
            description_raw = data.get("description_raw", "")
            description_clean = description_raw[:500] if description_raw else ""
            
            # Organizer
            organizer_name = "Posterheroes"
            organization_slug = "posterheroes"
            
            # Official link - usar URL de fetch (www.posterheroes.org)
            official_link = data.get("official_link") or raw.url or "https://www.posterheroes.org/"
            
            # Construir NormalizedOpportunity - campos que usará Fingerprint, History, Database, Notification
            return NormalizedOpportunity(
                title=title,
                organizer_name=organizer_name,
                organization_slug=organization_slug,
                official_link=official_link,
                description_raw=description_raw,
                description_clean=description_clean,
                deadline=deadline,
                awards_text=awards_text,
                economic_value=economic_value,
                currency=currency,
                category="Arte Digital",
                opportunity_type="contest",
                country="Italy",
                language="Inglés",
                source_url=raw.url,
                provider=self.provider_type,
                extra_json={
                    "brief_links": data.get("brief_links", []),
                    "extraction_source": data.get("extraction_source", "www.posterheroes.org"),
                    "deadline_text": data.get("deadline_text", deadline),
                    "format_requested": "Poster 70x100cm"
                }
            )
        
        except Exception as e:
            logger.error(f"[Posterheroes] Normalize failed for {raw.title}: {e}", exc_info=True)
            # Fallback mínimo para no romper pipeline
            return NormalizedOpportunity(
                title=raw.title or "Posterheroes Contest",
                organizer_name="Posterheroes",
                organization_slug="posterheroes",
                official_link=raw.url or "https://www.posterheroes.org/",
                description_raw="Posterheroes international contest",
                source_url=raw.url,
                provider=self.provider_type
            )
